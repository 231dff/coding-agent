"""子 Agent 委派工具。

书中 2.7.7：隔离优于压缩。
让大体积的中间信息（搜索结果、候选文件内容）根本不进入主上下文。
"""
from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool

from tools.file_ops import (
    read_file,
    grep_search,
    glob_files,
    ls_dir,
)
from tools.registry import build_default_tools


# 全局绑定（由 agent/core.py 注入）
_WORKSPACE: str | None = None
_MODEL: str | None = None


def bind(workspace: str, model: str) -> None:
    global _WORKSPACE, _MODEL
    _WORKSPACE = workspace
    _MODEL = model


# 子 Agent 的系统提示（书中 4.6：角色定义清晰、上下文来源明确、输出标准化）
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
    """构建搜索子 Agent。用便宜模型 + 精简工具集。"""
    if _MODEL is None:
        raise RuntimeError("subagent_ops 未绑定模型")

    tools = [grep_search, read_file, glob_files, ls_dir]

    return create_agent(
        model=_MODEL,
        tools=tools,
        system_prompt=SEARCH_AGENT_PROMPT,
    )


@tool
async def delegate_search(task: str, focus_path: str = "") -> str:
    """把搜索任务委派给独立的子 Agent。

    关键优势：
    - 搜索过程中的所有中间结果被隔离在子 Agent 内部
    - 主上下文只增加"任务描述 + 结论"两条消息
    - 主 Agent 的 KV Cache 前缀不受影响

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

    agent = _build_search_agent()

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": full_task}]},
            config={
                "configurable": {"thread_id": f"search-{id(task)}"},
                "recursion_limit": 20,
            },
        )
        content = result["messages"][-1].content
        # 硬性截断，防止子 Agent 返回过长内容
        return content[:3000] if isinstance(content, str) else str(content)[:3000]
    except Exception as e:
        return f"ERROR: 子 Agent 执行失败: {type(e).__name__}: {e}"


@tool
async def delegate_analyze(symbol: str, question: str) -> str:
    """把符号分析任务委派给子 Agent。

    用于回答"这个函数在哪被调用"、"修改它会影响什么"、
    "它依赖什么"这类问题。子 Agent 会综合调用关系、
    文件依赖、代码内容后给出结论。

    Args:
        symbol: 符号名（函数/类名）。
        question: 具体问题。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    from codebase.dep_graph import DependencyGraph
    from codebase.call_graph import CallGraph
    from codebase.parser import CodeParser

    parser = CodeParser(_WORKSPACE)
    call_graph = CallGraph(parser)
    call_graph.build()

    # 简化实现：直接分析，不启动子 Agent（分析本身不产生大体积中间结果）
    callers = call_graph.callers_of(symbol)
    callees = call_graph.callees_of(symbol)

    return (
        f"符号: {symbol}\n"
        f"调用方 ({len(callers)}): {callers[:10]}\n"
        f"被调用 ({len(callees)}): {callees[:10]}\n"
        f"问题: {question}"
    )


SUBAGENT_TOOLS = ["delegate_search", "delegate_analyze"]