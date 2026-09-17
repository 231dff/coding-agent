"""经验提炼与存储。

从成功轨迹里提炼可复用的工作模式，写入 lessons.md。
下次会话时注入 system prompt。

设计：
- 显式触发（/learn 命令），不自动跑
- 从轨迹 JSONL 读，不依赖 checkpointer
- 按类别组织，行级去重
- 上限 60 行（约 1200 token）

存储位置：<project>/.coding-agent/memory/lessons.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

# ============================================================
# 存储路径
# ============================================================


def lessons_path(meta_dir: Path) -> Path:
    """返回经验文件路径。"""
    return meta_dir / "memory" / "lessons.md"


def load_lessons(meta_dir: Path) -> str:
    """读取经验内容。不存在时返回空字符串。"""
    path = lessons_path(meta_dir)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# ============================================================
# 轨迹读取
# ============================================================


def list_recent_trajectories(traj_dir: Path, n: int = 20) -> list[Path]:
    """列出最近的 N 个轨迹文件（按修改时间倒序）。"""
    if not traj_dir.is_dir():
        return []

    files = sorted(
        traj_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[:n]


def read_trajectory(path: Path) -> list[dict]:
    """读一个 JSONL 轨迹文件，返回事件列表。

    容错：跳过非法行，不抛异常。
    """
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return events


# ============================================================
# 成功判定
# ============================================================


def is_trajectory_successful(events: list[dict]) -> tuple[bool, str]:
    """启发式判断一条轨迹是否成功。

    规则：
    - 总事件数 >= 10（太短不算）
    - 工具调用失败率 < 30%
    - 最后一条事件不是 tool_result（说明卡在工具里）

    Returns:
        (is_successful, reason)
    """
    if len(events) < 10:
        return False, f"太短（{len(events)} 条事件）"

    tool_results = [e for e in events if e.get("event") == "tool_result"]
    if not tool_results:
        return False, "无工具调用"

    failures = sum(1 for e in tool_results if not e.get("success", True))
    fail_rate = failures / max(1, len(tool_results))
    if fail_rate >= 0.3:
        return False, f"失败率过高（{fail_rate:.0%}）"

    # 最后一条事件不能卡在工具上
    last = events[-1]
    if last.get("event") == "tool_result":
        return False, "以工具结果结尾（可能未完成）"

    return True, "成功"


def summarize_trajectory(events: list[dict], max_chars: int = 2000) -> str:
    """把轨迹压缩成文本摘要（给 LLM 看）。"""
    lines: list[str] = []
    for e in events:
        ev = e.get("event", "")
        if ev == "message":
            role = e.get("role", "?")
            content = str(e.get("content", ""))[:200]
            lines.append(f"[{role}] {content}")
        elif ev == "tool_call":
            name = e.get("name", "?")
            args = e.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)[:100]
            lines.append(f"[call {name}] {args_str}")
        elif ev == "tool_result":
            name = e.get("name", "?")
            ok = "✓" if e.get("success") else "✗"
            output = str(e.get("output", ""))[:150]
            lines.append(f"[result {name} {ok}] {output}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n..."
    return text


# ============================================================
# 提炼提示词
# ============================================================

_EXTRACT_PROMPT = """你是一个经验提炼器。请从下面的 Agent 轨迹中，提炼出**可复用的工程经验**。

## 判断标准

**只记录**：
- 成功完成某类任务的步骤模式（"做 X 时应该先 Y 再 Z"）
- 工具使用的技巧（"读大文件应该用 offset/limit"）
- 避免踩坑的方法（"改代码前先 grep 引用"）
- 反复出现的有效策略

**不要记录**：
- 一次性的具体任务（"这次改了 analysis_agent.py"）
- 通用编程常识（"要写测试"）
- 模型自己的推理过程
- 失败的操作

## 输出格式

按类别输出 Markdown 列表。没有可提炼的经验就输出"（无）"。

格式示例：

## 文件操作
- 读大文件用 offset/limit 分页，不要一次全读

## 代码定位
- 修改函数前先 grep 所有调用方

## 测试
- 改完代码后立即跑相关测试，不要等全跑

每条不超过 40 字，最多 6 条。宁可少写，不要编造。

## 轨迹

{trajectory}
"""


# ============================================================
# 提炼
# ============================================================


def extract_lessons_from_trajectories(
    llm: BaseChatModel,
    traj_dir: Path,
    max_trajectories: int = 10,
) -> str:
    """从最近的轨迹里提炼经验。

    只处理成功轨迹。把多条轨迹的提炼结果合并。

    Returns:
        Markdown 格式的经验文本。无内容时返回空字符串。
    """
    files = list_recent_trajectories(traj_dir, n=max_trajectories * 2)
    if not files:
        return ""

    all_extracted: list[str] = []
    used = 0

    for path in files:
        if used >= max_trajectories:
            break

        events = read_trajectory(path)
        ok, _ = is_trajectory_successful(events)
        if not ok:
            continue

        summary = summarize_trajectory(events)
        if not summary:
            continue

        prompt = _EXTRACT_PROMPT.format(trajectory=summary)
        try:
            response = llm.invoke(prompt)
            content = getattr(response, "content", "")
            if not isinstance(content, str):
                content = str(content)
            cleaned = _clean_extracted(content)
            if cleaned:
                all_extracted.append(cleaned)
                used += 1
        except Exception:
            continue

    if not all_extracted:
        return ""

    return "\n\n".join(all_extracted)


def _clean_extracted(text: str) -> str:
    """清理 LLM 输出：去掉围栏、去掉"（无）"、去掉空标题。"""
    text = text.strip()

    # 去掉 markdown 围栏
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    # 无内容判断
    if not text or text in ("（无）", "(无)", "无"):
        return ""
    if re.fullmatch(r"[（(]?无[）)]?", text):
        return ""

    # 去掉空标题
    lines = text.splitlines()
    cleaned: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            j = i + 1
            has_item = False
            while j < len(lines) and not lines[j].startswith("#"):
                if lines[j].strip().startswith("-"):
                    has_item = True
                    break
                j += 1
            if has_item:
                cleaned.append(line)
        else:
            cleaned.append(line)
        i += 1

    return "\n".join(cleaned).strip()


# ============================================================
# 写入 + 去重
# ============================================================


def _normalize_line(line: str) -> str:
    """归一化一行，用于去重。"""
    s = line.strip().lstrip("-").strip().lower()
    s = re.sub(r"[\s，。、；：]+", "", s)
    return s


def merge_into_lessons(
    meta_dir: Path,
    new_content: str,
    max_lines: int = 60,
) -> str:
    """把新提炼的经验合并进 lessons.md。

    和 user_preference 一样的策略：
    - 按类别分组
    - 行级去重
    - 超限时按类别均摊截断
    """
    path = lessons_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_lessons(meta_dir)

    existing_groups = _parse_md_groups(existing)
    new_groups = _parse_md_groups(new_content)

    merged: dict[str, list[str]] = {}
    seen_normalized: set[str] = set()

    for cat, lines in existing_groups.items():
        merged.setdefault(cat, [])
        for line in lines:
            n = _normalize_line(line)
            if n and n not in seen_normalized:
                merged[cat].append(line)
                seen_normalized.add(n)

    for cat, lines in new_groups.items():
        merged.setdefault(cat, [])
        for line in lines:
            n = _normalize_line(line)
            if n and n not in seen_normalized:
                merged[cat].append(line)
                seen_normalized.add(n)

    output_lines = ["# 工程经验", ""]

    total = sum(len(v) for v in merged.values())
    if total > max_lines:
        per_cat = max(1, max_lines // max(1, len(merged)))
        for cat in merged:
            merged[cat] = merged[cat][:per_cat]

    for cat, lines in merged.items():
        if not lines:
            continue
        output_lines.append(f"## {cat}")
        for line in lines:
            if not line.strip().startswith("-"):
                line = f"- {line.strip()}"
            output_lines.append(line)
        output_lines.append("")

    result = "\n".join(output_lines).rstrip() + "\n"
    path.write_text(result, encoding="utf-8")
    return result


def _parse_md_groups(text: str) -> dict[str, list[str]]:
    """把 Markdown 解析成 {category: [lines]}。"""
    groups: dict[str, list[str]] = {}
    current_cat: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            current_cat = stripped[3:].strip()
            groups.setdefault(current_cat, [])
        elif stripped.startswith("# "):
            continue
        elif stripped.startswith("- ") and current_cat:
            groups[current_cat].append(stripped)

    return groups


def stats(meta_dir: Path) -> dict:
    """返回经验文件的统计。"""
    path = lessons_path(meta_dir)
    if not path.is_file():
        return {"exists": False, "lines": 0, "categories": 0}

    text = path.read_text(encoding="utf-8")
    groups = _parse_md_groups(text)
    return {
        "exists": True,
        "path": str(path),
        "lines": sum(len(v) for v in groups.values()),
        "categories": len(groups),
    }
