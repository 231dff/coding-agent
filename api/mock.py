"""Mock 模式的 SSE 事件流。

用途：
1. 前端独立开发，无需等后端全部就绪
2. 集成测试中的确定性输入
3. 演示和 E2E 测试
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator


def sse(event: str, data: dict) -> str:
    """格式化为 SSE 事件块。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def mock_chat_stream(
    message: str,
    session_id: str,
    scenario: str = "default",
) -> AsyncIterator[str]:
    """模拟一次对话的完整事件流。

    scenario:
      - "default": 普通对话，含 1 次工具调用
      - "code": 含代码块输出
      - "multi_tool": 多次工具调用
      - "error": 中途报错
      - "slow": 慢速 token 流
      - "approval": 触发审批流程
    """
    user_id = session_id or uuid.uuid4().hex[:12]

    if scenario == "error":
        async for chunk in _scenario_error(user_id):
            yield chunk
        return

    if scenario == "slow":
        async for chunk in _scenario_slow(user_id, message):
            yield chunk
        return

    if scenario == "multi_tool":
        async for chunk in _scenario_multi_tool(user_id, message):
            yield chunk
        return

    if scenario == "code":
        async for chunk in _scenario_code(user_id, message):
            yield chunk
        return

    if scenario == "approval":
        async for chunk in _scenario_approval(user_id, message):
            yield chunk
        return

    async for chunk in _scenario_default(user_id, message):
        yield chunk


async def _scenario_default(session_id: str, message: str) -> AsyncIterator[str]:
    """默认场景：1 次工具调用 + 回复。"""
    for token in ["好的，", "我来", "读取", "相关", "文件..."]:
        yield sse("token", {"content": token, "session_id": session_id})
        await asyncio.sleep(0.05)

    tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
    yield sse("tool_start", {
        "tool_call_id": tool_call_id,
        "tool_name": "read_file",
        "args": {"path": "calc.py"},
        "timestamp": time.time(),
    })
    await asyncio.sleep(0.3)

    yield sse("tool_end", {
        "tool_call_id": tool_call_id,
        "tool_name": "read_file",
        "output": "def add(a, b):\n    return a + b\n",
        "timestamp": time.time(),
    })

    for token in ["\n\n", "文件里", "有一个 `add` 函数，", "实现是正确的。"]:
        yield sse("token", {"content": token, "session_id": session_id})
        await asyncio.sleep(0.05)

    yield sse("done", {"session_id": session_id})


async def _scenario_code(session_id: str, message: str) -> AsyncIterator[str]:
    """输出含代码块的回复。"""
    for token in ["这是", "修复方案：", "\n\n```python\n", "def add(a, b):\n", "    return a + b\n", "```\n\n"]:
        yield sse("token", {"content": token, "session_id": session_id})
        await asyncio.sleep(0.08)
    yield sse("done", {"session_id": session_id})


async def _scenario_multi_tool(session_id: str, message: str) -> AsyncIterator[str]:
    """多次工具调用。"""
    yield sse("token", {"content": "我先分析影响范围，再修改文件。", "session_id": session_id})
    await asyncio.sleep(0.1)

    tools = [
        ("analyze_impact", {"symbol_name": "process"}, "发现 3 个调用方"),
        ("read_file", {"path": "service.py"}, "def process(data): ..."),
        ("edit_file", {"path": "service.py", "old_string": "process", "new_string": "handle"}, "OK: 已编辑"),
        ("run_tests", {"command": "pytest"}, "5 passed"),
    ]

    for tool_name, args, output in tools:
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        yield sse("tool_start", {
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "args": args,
            "timestamp": time.time(),
        })
        await asyncio.sleep(0.4)
        yield sse("tool_end", {
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "output": output,
            "timestamp": time.time(),
        })
        await asyncio.sleep(0.1)

    for token in ["所有调用方", "已同步修改，", "测试通过。"]:
        yield sse("token", {"content": token, "session_id": session_id})
        await asyncio.sleep(0.05)

    yield sse("done", {"session_id": session_id})


async def _scenario_error(session_id: str) -> AsyncIterator[str]:
    """中途报错。"""
    yield sse("token", {"content": "开始执行...", "session_id": session_id})
    await asyncio.sleep(0.2)

    yield sse("error", {
        "source": "tool",
        "tool_name": "execute",
        "message": "Command failed: pytest returned exit code 1",
    })
    await asyncio.sleep(0.2)

    yield sse("error", {
        "source": "server",
        "message": "上下文压缩熔断触发（连续 3 次失败）",
    })

    yield sse("done", {"session_id": session_id})


async def _scenario_slow(session_id: str, message: str) -> AsyncIterator[str]:
    """慢速 token 流，用于测试中断。"""
    text = "这是一个慢速响应，用于测试前端的流式渲染和中断功能。每个字符之间有 200ms 的延迟。"
    for char in text:
        yield sse("token", {"content": char, "session_id": session_id})
        await asyncio.sleep(0.2)
    yield sse("done", {"session_id": session_id})


async def _scenario_approval(session_id: str, message: str) -> AsyncIterator[str]:
    """审批场景。

    流程：
    1. 输出一段话
    2. 发出 approval_required 事件
    3. 等待前端通过 POST /api/chat/approve 注入决策（最多 30 秒）
    4. 根据决策继续：批准 → 执行工具；拒绝 → 告知用户
    """
    from api.approval import approval_manager

    yield sse("token", {
        "content": "我需要执行一个命令来验证测试。",
        "session_id": session_id,
    })
    await asyncio.sleep(0.3)

    tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
    thread_id = session_id
    checkpoint_id = f"ckpt-{uuid.uuid4().hex[:8]}"

    # 创建审批请求
    approval = await approval_manager.request(
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name="execute",
        args={"command": "pytest tests/ -v", "timeout": 120},
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        reason="执行 shell 命令: pytest tests/ -v",
    )

    # 发出审批事件
    yield sse("approval_required", {
        "session_id": session_id,
        "approval_id": approval.id,
        "tool_call_id": tool_call_id,
        "tool_name": "execute",
        "args": approval.args,
        "reason": approval.reason,
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "timestamp": time.time(),
    })

    # 如果是危险命令，已经被自动拒绝，直接走拒绝路径
    if approval.decision == "reject" and approval.decided_by == "system":
        yield sse("error", {
            "source": "tool",
            "tool_name": "execute",
            "message": f"操作被自动拒绝: {approval.reason}",
        })
        yield sse("token", {
            "content": "\n\n该操作被系统自动拒绝。",
            "session_id": session_id,
        })
        yield sse("done", {"session_id": session_id})
        return

    # 等待用户决策
    resolved = await approval_manager.wait_decision(approval.id)

    if resolved.decision == "reject":
        yield sse("error", {
            "source": "tool",
            "tool_name": "execute",
            "message": f"用户拒绝执行: {resolved.reason}",
        })
        yield sse("token", {
            "content": "\n\n好的，已跳过该命令。",
            "session_id": session_id,
        })
        yield sse("done", {"session_id": session_id})
        return

    # 批准（或编辑后批准）
    final_args = resolved.edited_args or approval.args
    yield sse("token", {
        "content": "\n\n已批准，开始执行...",
        "session_id": session_id,
    })
    await asyncio.sleep(0.2)

    yield sse("tool_start", {
        "tool_call_id": tool_call_id,
        "tool_name": "execute",
        "args": final_args,
        "timestamp": time.time(),
    })
    await asyncio.sleep(0.6)

    yield sse("tool_end", {
        "tool_call_id": tool_call_id,
        "tool_name": "execute",
        "output": (
            "============================= test session starts =============================\n"
            "collected 5 items\n\n"
            "tests/test_calc.py::test_add PASSED                                       [ 20%]\n"
            "tests/test_calc.py::test_sub PASSED                                       [ 40%]\n"
            "tests/test_calc.py::test_mul PASSED                                       [ 60%]\n"
            "tests/test_calc.py::test_div PASSED                                       [ 80%]\n"
            "tests/test_calc.py::test_edge PASSED                                      [100%]\n\n"
            "\x1b[32m5 passed in 0.42s\x1b[0m"
        ),
        "timestamp": time.time(),
    })

    yield sse("token", {
        "content": "\n\n测试全部通过，任务完成。",
        "session_id": session_id,
    })

    yield sse("done", {"session_id": session_id})