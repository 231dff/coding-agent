"""P4: 统计数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskStats:
    """单个任务的聚合视图。"""

    session_id: str
    ts: float
    task: str
    verdict: str
    success: bool
    tool_calls: int = 0
    files_changed: int = 0
    reviewer_verdict: str = ""
    reviewer_confidence: float = 0.0
    failed_dimensions: list[str] = field(default_factory=list)


@dataclass
class StatsSnapshot:
    """整个系统的统计快照。"""

    # 任务总览
    total_tasks: int = 0
    success_count: int = 0
    fail_count: int = 0
    uncertain_count: int = 0
    veto_count: int = 0

    # 任务明细
    tasks: list[TaskStats] = field(default_factory=list)

    # 聚合
    tool_usage: dict[str, int] = field(default_factory=dict)
    failed_dimensions: dict[str, int] = field(default_factory=dict)
    uncertain_dimensions: dict[str, int] = field(default_factory=dict)
    reviewer_distribution: dict[str, int] = field(default_factory=dict)

    # 时间序列（最近 7 天）
    # list of (date_str, total, success)
    daily: list[tuple[str, int, int]] = field(default_factory=list)

    # 成本
    total_cost_usd: float = 0.0
    cost_by_model: dict[str, float] = field(default_factory=dict)

    # 健康度
    avg_tool_calls: float = 0.0
    top_errors: list[str] = field(default_factory=list)
