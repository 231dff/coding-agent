"""Day 24: 测试执行-分析-修复循环。

核心机制：
    执行测试 → 分析错误 → 生成修复 → 重新测试
    连续 N 次失败 → 中断，请求人工介入
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from agent.state import RepairState


@dataclass
class TestResult:
    """测试执行结果。"""
    passed: bool
    total: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""


def parse_test_output(output: str) -> TestResult:
    """解析 pytest 输出为结构化结果。"""
    result = TestResult(passed=False, raw_output=output)

    # 匹配 "5 passed" / "3 failed" 等
    passed_match = re.search(r"(\d+)\s+passed", output)
    failed_match = re.search(r"(\d+)\s+failed", output)
    error_match = re.search(r"(\d+)\s+error", output)

    if passed_match:
        result.total += int(passed_match.group(1))
    if failed_match:
        result.failed = int(failed_match.group(1))
        result.total += result.failed
    if error_match:
        result.failed += int(error_match.group(1))
        result.total += int(error_match.group(1))

    result.passed = result.failed == 0 and result.total > 0

    # 提取失败用例名
    for line in output.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            result.errors.append(line.strip())

    return result


def build_repair_graph(agent, sandbox_exec, checkpointer):
    """构建测试修复 StateGraph。

    Args:
        agent: create_agent 构建的 Agent。
        sandbox_exec: 沙箱执行函数 (command) -> ExecResult。
        checkpointer: LangGraph checkpointer。
    """

    def run_tests(state: RepairState) -> dict:
        """执行测试命令。"""
        # 默认测试命令，可从状态中读取
        cmd = "pytest tests/ -v --tb=short 2>&1 | head -100"
        result = sandbox_exec(cmd)
        output = result.stdout + result.stderr

        test_result = parse_test_output(output)

        return {
            "test_passed": test_result.passed,
            "test_output": output,
            "messages": [AIMessage(content=f"测试结果: {'通过' if test_result.passed else '失败'}\n{output[:2000]}")],
        }

    def analyze_and_fix(state: RepairState) -> dict:
        """分析错误并尝试修复。"""
        iteration = state.get("iteration_count", 0) + 1
        test_output = state.get("test_output", "")

        prompt = (
            f"测试失败。请分析错误并修复。\n\n"
            f"测试输出:\n{test_output[:3000]}\n\n"
            f"这是第 {iteration} 次尝试。请只修改必要的代码。"
        )

        # 调用 Agent 修复
        result = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": "repair-loop"}},
        )

        return {
            "iteration_count": iteration,
            "messages": [result["messages"][-1]],
        }

    def route_after_test(state: RepairState) -> Literal["analyze_and_fix", "end"]:
        """路由：测试通过则结束，失败则修复。"""
        if state.get("test_passed"):
            return "end"

        iteration = state.get("iteration_count", 0)
        max_iter = state.get("max_iterations", 3)

        if iteration >= max_iter:
            return "end"  # 超过最大迭代，放弃

        return "analyze_and_fix"

    # 构建图
    graph = StateGraph(RepairState)

    graph.add_node("run_tests", run_tests)
    graph.add_node("analyze_and_fix", analyze_and_fix)

    graph.add_edge(START, "run_tests")
    graph.add_conditional_edges(
        "run_tests",
        route_after_test,
        {"analyze_and_fix": "analyze_and_fix", "end": END},
    )
    graph.add_edge("analyze_and_fix", "run_tests")  # 修复后重新测试

    return graph.compile(checkpointer=checkpointer)