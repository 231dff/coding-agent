"""Day 23: 任务规划状态定义。"""

from __future__ import annotations

from collections.abc import Sequence
from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage


class PlanningState(TypedDict):
    """任务规划状态。

    使用 Annotated + operator.add 让 messages 自动追加，
    无需手动管理列表。
    """

    # 对话消息（自动追加）
    messages: Annotated[Sequence[BaseMessage], add]

    # 规划阶段
    requirement: str  # 原始需求
    plan: list[str]  # 拆解后的步骤
    current_step: int  # 当前步骤索引
    step_results: list[str]  # 每步的结果

    # 执行阶段
    files_changed: list[str]  # 修改的文件
    test_passed: bool  # 测试是否通过
    test_output: str  # 测试输出
    iteration_count: int  # 修复迭代次数

    # 终止条件
    should_end: bool
    error: str | None


class RepairState(TypedDict):
    """测试修复循环状态。"""

    messages: Annotated[Sequence[BaseMessage], add]
    iteration_count: int
    max_iterations: int
    test_passed: bool
    test_output: str
    files_changed: list[str]
    should_end: bool
    error: str | None
