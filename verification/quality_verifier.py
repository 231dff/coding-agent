from __future__ import annotations

import json
from typing import Any, Callable

from .events import TrajEvent
from .schema import DimensionResult, Severity, Verdict


DEFAULT_CODING_RUBRIC = {
    "dimensions": [
        {"name": "change_scope", "severity": "medium",
         "levels": {"4": "改动最小、仅触及必要文件",
                    "3": "有少量冗余改动",
                    "2": "涉及不相关文件",
                    "1": "大面积重写"}},
    ]
}


class QualityVerifier:
    """
    质量层：可选。没有传 judge 时返回 UNCERTAIN，不阻断流程。
    judge 签名: (prompt: str) -> str
    """

    def __init__(self, judge: Callable[[str], str] | None = None):
        self.judge = judge

    def verify(self, task_id: str, events: list[TrajEvent]) -> list[DimensionResult]:
        if self.judge is None:
            return [DimensionResult(
                name="quality_judge",
                verdict=Verdict.UNCERTAIN,
                severity=Severity.LOW,
                confidence=0.0,
                reason="未配置 LLM Judge，质量层跳过",
            )]

        prompt = self._build_prompt(task_id, events)
        try:
            raw = self.judge(prompt)
            parsed = json.loads(raw)
        except Exception as e:
            return [DimensionResult(
                name="quality_judge",
                verdict=Verdict.UNCERTAIN,
                severity=Severity.LOW,
                confidence=0.0,
                reason=f"Judge 调用失败: {e}",
            )]

        results = []
        for dim in DEFAULT_CODING_RUBRIC["dimensions"]:
            item = parsed.get(dim["name"], {})
            results.append(DimensionResult(
                name=dim["name"],
                verdict=Verdict(item.get("verdict", "uncertain")),
                severity=Severity(dim["severity"]),
                confidence=float(item.get("confidence", 0.5)),
                reason=item.get("reason", ""),
            ))
        return results

    @staticmethod
    def _build_prompt(task_id: str, events: list[TrajEvent]) -> str:
        lines = []
        for e in events:
            if e.type == "tool_call":
                lines.append(f"[{e.line_no}] CALL {e.name} {e.args}")
            elif e.type == "tool_result":
                lines.append(
                    f"[{e.line_no}] RESULT {e.name} success={e.success} "
                    f"{(e.content or '')[:120]}"
                )
        return (
            f"Task {task_id}. 请按 Rubric 打分（严格 JSON）。\n"
            f"Rubric: {json.dumps(DEFAULT_CODING_RUBRIC, ensure_ascii=False)}\n"
            f"轨迹:\n" + "\n".join(lines)
        )