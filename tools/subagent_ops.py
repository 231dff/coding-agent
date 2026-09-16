"""子 Agent 委派工具。

关键改动：
- 搜索子 Agent 单例，避免每次新建
- delegate_analyze 复用主 Agent 已构建的 call_graph
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from tools.file_ops import (
    glob_files,
    grep_search,
    ls_dir,
    read_file,
)

_WORKSPACE: str | None = None
_MODEL: str | None = None
_CALL_GRAPH: Any = None
_SEARCH_AGENT: Any = None


def bind(workspace: str, model: str) -> None:
    global _WORKSPACE, _MODEL, _SEARCH_AGENT
    _WORKSPACE = workspace
    _MODEL = model
    _SEARCH_AGENT = None  # 重置单例


def bind_graphs(call_graph: Any) -> None:
    global _CALL_GRAPH
    _CALL_GRAPH = call_graph


SEARCH_AGENT_PROMPT = """你是代码搜索专家。

## 职责
在代码库中定位与任务相关的代码，返回结构化结论。

## 工具使用
- grep_search: 优先用精确关键词
- read_file: 只在确认候选后用，按行号读取
- glob_files: 找文件路径
- ls_dir: 理解目录结构

## 输出规范（严格遵守）
只返回以下 JSON 格式，不含其他文字：
{
  "files": [
    {"path": "相对路径", "line": 行号, "reason": "为什么相关"}
  ],
  "summary": "一句话总结发现的模式或结论",
  "confidence": "high | medium | low"
}

## 边界
- NEVER 读取整个文件，只读关键行段
- NEVER 返回超过 10 个文件
- 若未找到相关内容，返回 {"files": [], "summary": "未找到", "confidence": "low"}
"""


def _build_search_agent():
    if _MODEL is None:
        raise RuntimeError("subagent_ops 未绑定模型")
    tools = [grep_search, read_file, glob_files, ls_dir]
    return create_agent(
        model=_MODEL,
        tools=tools,
        system_prompt=SEARCH_AGENT_PROMPT,
    )


def _get_search_agent():
    global _SEARCH_AGENT
    if _SEARCH_AGENT is None:
        _SEARCH_AGENT = _build_search_agent()
    return _SEARCH_AGENT


@tool
async def delegate_search(task: str, focus_path: str = "") -> str:
    """把搜索任务委派给独立的子 Agent。

    当需要在大代码库中搜索时，ALWAYS 优先用此工具，
    而非直接调用 grep_search 或 semantic_search。

    Args:
        task: 搜索任务的自然语言描述。
        focus_path: 限定搜索路径（可选）。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    full_task = task
    if focus_path:
        full_task += f"\n\n限定搜索路径: {focus_path}"

    agent = _get_search_agent()

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": full_task}]},
            config={
                "configurable": {"thread_id": f"search-{id(task)}"},
                "recursion_limit": 20,
            },
        )
        content = result["messages"][-1].content
        return content[:3000] if isinstance(content, str) else str(content)[:3000]
    except Exception as e:
        return f"ERROR: 子 Agent 执行失败: {type(e).__name__}: {e}"


@tool
async def delegate_analyze(symbol: str, question: str) -> str:
    """把符号分析任务委派给子 Agent。

    Args:
        symbol: 符号名（函数/类名）。
        question: 具体问题。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    if _CALL_GRAPH is None:
        return "ERROR: 调用图未初始化"

    callers = _CALL_GRAPH.callers_of(symbol)
    callees = _CALL_GRAPH.callees_of(symbol)

    return (
        f"符号: {symbol}\n"
        f"调用方 ({len(callers)}): {callers[:10]}\n"
        f"被调用 ({len(callees)}): {callees[:10]}\n"
        f"问题: {question}"
    )


SUBAGENT_TOOLS = ["delegate_search", "delegate_analyze"]
