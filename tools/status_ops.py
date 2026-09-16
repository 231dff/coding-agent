"""状态栏工具：让 Agent 可以主动操作 TODO 列表。

不暴露时间戳/工具计数这些自动维护的状态（避免 Agent 手动篡改）。
只暴露 TODO 的增删改查。
"""

from __future__ import annotations

from langchain.tools import tool

from context.status_bar import AgentStatusBar

_BAR: AgentStatusBar | None = None


def bind(bar: AgentStatusBar) -> None:
    global _BAR
    _BAR = bar


@tool
def add_todo(text: str) -> str:
    """向当前任务列表添加一项 TODO。

    当任务包含多个步骤时，ALWAYS 先用此工具列出所有步骤，
    然后逐个执行、逐个更新状态。这能防止遗漏子任务。

    Args:
        text: TODO 内容，一句话描述。
    """
    if _BAR is None:
        return "ERROR: 状态栏未初始化"
    tid = _BAR.todo_add(text)
    return f"OK: 已添加 {tid}: {text}"


@tool
def update_todo(todo_id: str, status: str) -> str:
    """更新 TODO 项的状态。

    每完成一个步骤后，ALWAYS 立即调用此工具更新状态。
    这能让 Agent 在长任务中保持目标感知。

    Args:
        todo_id: TODO 的 ID（如 T1）。
        status: 新状态，取值 pending / in_progress / completed / cancelled。
    """
    if _BAR is None:
        return "ERROR: 状态栏未初始化"
    valid = ("pending", "in_progress", "completed", "cancelled")
    if status not in valid:
        return f"ERROR: 状态必须是 {valid} 之一"
    ok = _BAR.todo_update(todo_id, status)
    return f"OK: {todo_id} → {status}" if ok else f"ERROR: 未知 TODO {todo_id}"


@tool
def list_todos() -> str:
    """列出当前所有 TODO 项及其状态。"""
    if _BAR is None:
        return "ERROR: 状态栏未初始化"
    if not _BAR.todos:
        return "(无 TODO)"
    lines = [item.to_line() for item in _BAR.todos.values()]
    return "\n".join(lines)


@tool
def rewrite_todos(items: str) -> str:
    """整体重写 TODO 列表。用于任务拆解后一次性设置所有步骤。

    Args:
        items: JSON 字符串，格式：[{"text": "...", "status": "pending"}, ...]
    """
    if _BAR is None:
        return "ERROR: 状态栏未初始化"
    import json

    try:
        parsed = json.loads(items)
    except json.JSONDecodeError as e:
        return f"ERROR: JSON 解析失败: {e}"
    if not isinstance(parsed, list):
        return "ERROR: 必须是数组"
    _BAR.todo_rewrite(parsed)
    return f"OK: 已设置 {len(parsed)} 项 TODO"


STATUS_TOOLS = ["add_todo", "update_todo", "list_todos", "rewrite_todos"]
