"""摘要聚合器（第 3 步）。

把同一 task_type 的多条 raw 摘要合并成 1 条 daily 摘要。
目的：减少检索噪声。

触发条件：
  - 未聚合的 raw 摘要数 >= threshold（默认 20）
  - 且该 task_type 至少有 2 条（单条没必要聚合）

不删除原始摘要——只打上 aggregated_into 标记。
"""

from __future__ import annotations

import json
import re
import time

from langchain_core.language_models.chat_models import BaseChatModel

from memory.session_summary import (
    SessionSummary,
    SessionSummaryRepository,
)

_AGGREGATE_PROMPT = """你是记忆整理师。下面是同一类型任务的 N 条摘要，请合并成 1 条 200 字以内的"总结式"摘要。

## 合并原则

1. **找出反复出现的模式**——比如同一个坑踩了多次、同类问题有共同解法
2. **保留通用经验**——比如"这个项目用 pytest"、"该模块改造前需要先跑 smoke test"
3. **丢弃一次性细节**——比如具体文件路径、具体时间戳、具体报错堆栈
4. **如果这批任务彼此没什么共性**，就诚实说"任务分散，无稳定模式"

## 输出格式

严格输出 JSON：

{{
  "summary": "合并后的总结（200 字内）",
  "key_facts": ["通用事实 1", "通用事实 2", "..."],
  "has_pattern": true
}}

- `has_pattern=true` 表示这批任务确实有共性
- `has_pattern=false` 表示彼此无关，聚合没意义（仍会保存，但标签为"分散"）

## 任务类型
{task_type}

## {n} 条摘要

{summaries}
"""


def _format_summaries(items: list[SessionSummary]) -> str:
    lines: list[str] = []
    for i, s in enumerate(items, 1):
        lines.append(f"[{i}] {s.summary}")
        if s.key_facts:
            lines.append(f"    事实: {' / '.join(s.key_facts)}")
    return "\n".join(lines)


def _parse_json(raw: str) -> dict | None:
    text = raw.strip()
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _extract_content(resp) -> str:
    c = getattr(resp, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(c)


def _aggregate_one_group(
    llm: BaseChatModel,
    task_type: str,
    items: list[SessionSummary],
) -> dict | None:
    """把一组同 task_type 的摘要合并。"""
    prompt = _AGGREGATE_PROMPT.format(
        task_type=task_type,
        n=len(items),
        summaries=_format_summaries(items),
    )

    try:
        resp = llm.invoke(prompt)
        raw = _extract_content(resp)
    except Exception:
        return None

    parsed = _parse_json(raw)
    if not parsed:
        return None

    summary = str(parsed.get("summary", "")).strip()
    if not summary:
        return None

    return {
        "summary": summary[:500],
        "key_facts": [str(x)[:100] for x in (parsed.get("key_facts") or [])[:5]],
        "has_pattern": bool(parsed.get("has_pattern", True)),
    }


def aggregate_summaries(
    llm: BaseChatModel,
    repo: SessionSummaryRepository | None = None,
    threshold: int = 20,
    min_group_size: int = 2,
    max_groups_per_run: int = 10,
) -> dict:
    """聚合 raw 摘要成 daily 摘要。

    Args:
        llm: 用于聚合的 LLM（建议用轻量模型）。
        repo: 摘要仓库。默认 user_card_repo 同款单例。
        threshold: 未聚合 raw 摘要达到多少条才触发。
        min_group_size: 一个 task_type 至少多少条才值得聚合。
        max_groups_per_run: 单次运行最多聚合多少组（防止一次调太多 LLM）。

    Returns:
        {"aggregated": N, "created": M, "skipped_groups": K}
    """
    if repo is None:
        from memory.session_summary import session_summary_repo

        repo = session_summary_repo()

    raw_items = repo.find_unaggregated_raw(limit=2000)
    if len(raw_items) < threshold:
        return {"aggregated": 0, "created": 0, "skipped_groups": 0}

    # 按 task_type 分组
    by_type: dict[str, list[SessionSummary]] = {}
    for s in raw_items:
        by_type.setdefault(s.task_type, []).append(s)

    # 只处理 >= min_group_size 的组，按组大小倒序（大组优先）
    eligible = [(tt, items) for tt, items in by_type.items() if len(items) >= min_group_size]
    eligible.sort(key=lambda kv: len(kv[1]), reverse=True)
    eligible = eligible[:max_groups_per_run]

    created = 0
    aggregated = 0
    skipped = 0

    for task_type, items in eligible:
        merged = _aggregate_one_group(llm, task_type, items)
        if not merged:
            skipped += 1
            continue

        new_summary = SessionSummary(
            session_id=f"agg-{task_type}-{int(time.time() * 1000)}",
            summary=merged["summary"],
            task_type=task_type,
            user_id=repo.user_id,
            key_facts=merged["key_facts"],
            success=True,
            level="daily",
            source_ids=[s.id for s in items],
        )
        repo.add(new_summary)
        repo.mark_aggregated([s.id for s in items], new_summary.id)
        created += 1
        aggregated += len(items)

    return {
        "aggregated": aggregated,
        "created": created,
        "skipped_groups": skipped,
    }
