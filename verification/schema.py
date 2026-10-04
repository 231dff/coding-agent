from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VETO = "veto"


class Evidence(BaseModel):
    line_no: Optional[int] = None
    ts: Optional[float] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    quote: Optional[str] = None
    source: str = "trajectory"


class DimensionResult(BaseModel):
    name: str
    verdict: Verdict
    severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrajectoryDiagnosis(BaseModel):
    task_id: str
    success: bool = False
    overall_verdict: Verdict = Verdict.UNCERTAIN
    veto_triggered: bool = False
    requires_human_review: bool = False
    dimensions: list[DimensionResult] = Field(default_factory=list)
    summary: str = ""

    def add(self, dim: DimensionResult) -> None:
        self.dimensions.append(dim)

        # ★ 只有 VETO 维度的 FAIL 才触发一票否决
        if dim.severity == Severity.VETO and dim.verdict == Verdict.FAIL:
            self.veto_triggered = True
            self.success = False
            self.overall_verdict = Verdict.FAIL

        # ★ 只有 MEDIUM+ 且低置信度才触发人工复核
        #   LOW 的 UNCERTAIN（如未配置 judge）不触发
        if dim.confidence < 0.6 and dim.severity in (
            Severity.MEDIUM, Severity.HIGH, Severity.VETO
        ):
            self.requires_human_review = True

    def get(self, name: str) -> Optional[DimensionResult]:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None
