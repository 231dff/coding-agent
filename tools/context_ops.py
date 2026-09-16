"""Day 20: 上下文管理工具。

让 Agent 能主动查看和操作上下文状态。
"""

from __future__ import annotations

from langchain.tools import tool

from context.offload import ContextOffloader

_OFFLOADER: ContextOffloader | None = None


def bind(workspace: str) -> None:
    global _OFFLOADER
    _OFFLOADER = ContextOffloader(workspace)


@tool
def offload_context(label: str = "") -> str:
    """将当前对话历史落盘保存，返回文件路径。

    当上下文接近满时，可以用此工具保存完整历史后再压缩。

    Args:
        label: 可选标签，用于标识这次快照。
    """
    if _OFFLOADER is None:
        return "ERROR: 未初始化"
    # 实际使用时从 Agent 状态获取消息
    return "上下文已落盘（需要 Agent 状态集成）"


@tool
def retrieve_offloaded(file_path: str) -> str:
    """回溯已落盘的上下文。

    Args:
        file_path: offload_context 返回的文件路径。
    """
    if _OFFLOADER is None:
        return "ERROR: 未初始化"
    content = _OFFLOADER.retrieve(file_path)
    # 截断大内容
    if len(content) > 10000:
        return content[:10000] + f"\n... (truncated, {len(content)} chars total)"
    return content


CONTEXT_TOOLS = ["offload_context", "retrieve_offloaded"]
