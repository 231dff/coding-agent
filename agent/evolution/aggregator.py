"""P2-2: 跨轨迹聚合。

读取最近 N 条经验记录，让 LLM 找出：
  1. 反复出现的失败模式
  2. 反复出现的好模式
  3. 候选规则（Prompt 补丁 / Skill 草稿）
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .store import ExperienceRecord

AGGREGATOR_SYSTEM_PROMPT = """你是一个经验分析师。你的任务是分析多轮 Agent 运行记录，找出：
1. **反复出现的失败模式**——同一个问题在多条轨迹里出现
2. **反复出现的好模式**——同一类成功经验
3. **候选规则**——可写入系统提示或 Skill 的通用规则

**关键原则**：
- 只提炼**多条**轨迹共同支持的模式，单次偶发不算
- 每条规则必须能追溯到具体证据（哪几条 session_id 支持）
- 优先找"可操作性"强的模式
- 不要重复已有规则

**输出严格 JSON**：
{
  "failure_patterns": [
    {
      "pattern": "一句话描述",
      "supporting_sessions": ["session-id-1", "session-id-2"],
      "dimension": "task_result",
      "suggested_fix": "可执行的修复方向"
    }
  ],
  "success_patterns": [
    {
      "pattern": "一句话描述",
      "supporting_sessions": ["session-id-1"],
      "why_it_works": "为什么有效"
    }
  ],
  "candidate_rules": [
    {
      "rule": "具体的规则文本，可直接粘贴到系统提示",
      "scope": "global",
      "evidence": ["session-id-1", "session-id-2"],
      "priority": "high"
    }
  ]
}

只输出 JSON，不要 Markdown 代码块。
"""


class ExperienceAggregator:
    def __init__(self, llm):
        self.llm = llm

    def aggregate(
        self,
        records: list[ExperienceRecord],
        existing_rules: str = "",
    ) -> dict[str, Any]:
        stats = self._statistical_summary(records)

        if not records:
            return {
                "failure_patterns": [],
                "success_patterns": [],
                "candidate_rules": [],
                "stats": stats,
            }

        prompt = self._build_prompt(records, existing_rules)

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=AGGREGATOR_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            raw = self._extract_content(response)
            parsed = self._parse_json(raw)
        except Exception as e:
            parsed = {
                "failure_patterns": [],
                "success_patterns": [],
                "candidate_rules": [],
                "error": f"LLM 调用失败: {e}",
            }

        parsed["stats"] = stats
        return parsed

    # ---------- 内部 ----------

    @staticmethod
    def _statistical_summary(records: list[ExperienceRecord]) -> dict[str, Any]:
        total = len(records)
        if total == 0:
            return {"total": 0}

        verdict_counter = Counter(r.verdict for r in records)
        veto_count = sum(1 for r in records if r.veto_triggered)
        review_counter = Counter(r.reviewer_verdict for r in records if r.reviewer_verdict)

        failed_dim_counter: Counter = Counter()
        uncertain_dim_counter: Counter = Counter()
        for r in records:
            for d in r.failed_dimensions:
                failed_dim_counter[d] += 1
            for d in r.uncertain_dimensions:
                uncertain_dim_counter[d] += 1

        return {
            "total": total,
            "verdict_distribution": dict(verdict_counter),
            "veto_count": veto_count,
            "reviewer_distribution": dict(review_counter),
            "top_failed_dimensions": failed_dim_counter.most_common(5),
            "top_uncertain_dimensions": uncertain_dim_counter.most_common(5),
        }

    @staticmethod
    def _build_prompt(records: list[ExperienceRecord], existing_rules: str) -> str:
        lines = ["## 最近运行记录", ""]
        for i, r in enumerate(records[:30], 1):
            lines.append(f"### 记录 {i}: {r.session_id}")
            lines.append(f"- 任务: {r.task[:200]}")
            lines.append(f"- 判定: {r.verdict} (success={r.success})")
            if r.veto_triggered:
                lines.append("- 触发一票否决")
            if r.failed_dimensions:
                lines.append(f"- 失败维度: {', '.join(r.failed_dimensions)}")
            if r.uncertain_dimensions:
                lines.append(f"- 不确定维度: {', '.join(r.uncertain_dimensions)}")
            if r.reviewer_verdict:
                lines.append(f"- Reviewer: {r.reviewer_verdict} (conf={r.reviewer_confidence:.2f})")
                for issue in r.reviewer_issues[:3]:
                    lines.append(
                        f"  - [{issue.get('severity', '?')}] {issue.get('description', '')}"
                    )
            if r.files_changed:
                lines.append(f"- 改动文件: {', '.join(r.files_changed[:5])}")
            lines.append("")

        parts = ["\n".join(lines)]
        if existing_rules:
            parts.extend(["", "## 已有规则（不要重复）", existing_rules[:3000]])
        parts.extend(["", "请基于以上记录，输出严格 JSON。"])
        return "\n".join(parts)

    @staticmethod
    def _extract_content(response) -> str:
        c = getattr(response, "content", "")
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

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass

        return {
            "failure_patterns": [],
            "success_patterns": [],
            "candidate_rules": [],
            "error": "无法解析聚合结果",
            "raw": raw[:500],
        }
