"""P4-2: Eval 框架数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    """一条回归测试案例。

    案例是**任务级别的**，不是单元测试级别的——
    因为它要覆盖 Agent 的整个行为（包括工具使用、审查、报告）。
    """

    case_id: str
    task: str
    category: str = "general"  # general / failure / veto / complex
    expected_verdict: str = "pass"  # pass / fail / uncertain
    expected_veto: bool = False
    # 用于对比的基线（历史 runs）
    baseline_verdict: str = ""
    baseline_session: str = ""
    notes: str = ""


@dataclass
class EvalResult:
    """跑一条案例的结果。"""

    case_id: str
    actual_verdict: str
    actual_veto: bool
    success: bool  # actual_verdict == expected_verdict
    diff_reason: str = ""
    failed_dimensions: list[str] = field(default_factory=list)
    tool_calls: int = 0
    elapsed_s: float = 0.0
    error: str = ""


@dataclass
class EvalReport:
    """一次完整 eval 的报告。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0

    results: list[EvalResult] = field(default_factory=list)

    # 与 baseline 对比
    regressions: list[str] = field(default_factory=list)  # case_id 列表
    improvements: list[str] = field(default_factory=list)
    unchanged: int = 0

    # 时间
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0
