"""Day 23: StateGraph 任务规划。

显式状态机：
    parse_requirement → explore → generate_plan → execute_step
        ↓                                              ↑
    validate_step ──────────────────────────────────────┘
        ↓ (完成)
    summarize
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agent.state import PlanningState

PLANNING_SYSTEM_PROMPT = """你是一个任务规划器。将用户需求拆解为可执行的步骤。

输出格式（严格 JSON）：
{
    "steps": [
        {"action": "read_file", "target": "src/main.py", "reason": "了解现有实现"},
        {"action": "edit_file", "target": "src/main.py", "reason": "添加新函数"},
        {"action": "execute", "target": "pytest tests/", "reason": "验证修改"}
    ]
}

原则：
1. 每步只做一件事，粒度足够小
2. 先探索再修改，先修改再验证
3. 步骤数控制在 3-7 个
4. 明确每步的目标文件和原因
"""


def build_planning_graph(agent, checkpointer):
    """构建任务规划 StateGraph。

    Args:
        agent: create_agent 构建的 Agent（作为子图节点）。
        checkpointer: LangGraph checkpointer（必须，否则 interrupt 无法工作）。
    """

    def parse_requirement(state: PlanningState) -> dict:
        """解析需求，提取关键信息。"""
        messages = state.get("messages", [])
        requirement = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                requirement = msg.content
                break
        return {"requirement": requirement}

    def explore(state: PlanningState) -> dict:
        """探索代码库（调用 Agent 做初步调查）。"""
        # 实际实现中，这里可以调用 repo_map / semantic_search
        return {"messages": [AIMessage(content="开始探索代码库...")]}

    def generate_plan(state: PlanningState) -> dict:
        """生成执行计划。

        TODO: 实际调用 LLM 时，用 state.get("requirement", "") 组装
              PLANNING_SYSTEM_PROMPT + requirement 一起发给模型。
              这里简化为占位。
        """
        plan = ["read_file", "edit_file", "execute"]
        return {"plan": plan, "current_step": 0}

    def execute_step(state: PlanningState) -> dict:
        """执行当前步骤。"""
        step_idx = state.get("current_step", 0)
        plan = state.get("plan", [])
        if step_idx >= len(plan):
            return {"should_end": True}

        step = plan[step_idx]
        result = f"已完成步骤 {step_idx + 1}: {step}"
        results = state.get("step_results", []) + [result]
        return {"step_results": results, "messages": [AIMessage(content=result)]}

    def validate_step(state: PlanningState) -> dict:
        """验证步骤结果。"""
        return {"current_step": state.get("current_step", 0) + 1}

    def route_after_validate(state: PlanningState) -> str:
        """路由：继续执行下一步还是结束。"""
        if state.get("should_end"):
            return "summarize"
        if state.get("current_step", 0) >= len(state.get("plan", [])):
            return "summarize"
        return "execute_step"

    def summarize(state: PlanningState) -> dict:
        """汇总结果。"""
        results = state.get("step_results", [])
        summary = f"任务完成。共执行 {len(results)} 个步骤。"
        return {"messages": [AIMessage(content=summary)]}

    # 构建图
    graph = StateGraph(PlanningState)

    graph.add_node("parse_requirement", parse_requirement)
    graph.add_node("explore", explore)
    graph.add_node("generate_plan", generate_plan)
    graph.add_node("execute_step", execute_step)
    graph.add_node("validate_step", validate_step)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "parse_requirement")
    graph.add_edge("parse_requirement", "explore")
    graph.add_edge("explore", "generate_plan")
    graph.add_edge("generate_plan", "execute_step")
    graph.add_edge("execute_step", "validate_step")
    graph.add_conditional_edges(
        "validate_step",
        route_after_validate,
        {"execute_step": "execute_step", "summarize": "summarize"},
    )
    graph.add_edge("summarize", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=["generate_plan"],
    )
