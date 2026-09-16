"""真实 Agent 模式的 SSE 事件流。"""

from __future__ import annotations

import asyncio
import queue
import time
import uuid
from collections.abc import AsyncIterator

from api.approval import approval_manager
from api.mock import sse


def _truncate(text: str, max_len: int = 5000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... (truncated, {len(text)} chars total)"


def _extract_tool_call_id(event: dict) -> str:
    data = event.get("data") or {}
    inp = data.get("input")
    if isinstance(inp, dict):
        tc_id = inp.get("tool_call_id")
        if tc_id:
            return str(tc_id)
    out = data.get("output")
    if hasattr(out, "tool_call_id") and out.tool_call_id:
        return str(out.tool_call_id)
    if isinstance(out, dict):
        tc_id = out.get("tool_call_id")
        if tc_id:
            return str(tc_id)
    return str(event.get("run_id", ""))


def _extract_tool_args(event: dict) -> dict:
    data = event.get("data") or {}
    inp = data.get("input")
    if isinstance(inp, dict):
        return inp
    if isinstance(inp, str):
        try:
            import json

            return json.loads(inp)
        except Exception:
            return {"raw": inp}
    return {}


async def _maybe_request_approval(
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    args: dict,
    thread_id: str,
    checkpoint_id: str,
) -> AsyncIterator[str]:
    if not approval_manager.is_sensitive(tool_name):
        return

    approval = await approval_manager.request(
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args=args,
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
    )
    yield sse(
        "approval_required",
        {
            "session_id": session_id,
            "approval_id": approval.id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": args,
            "reason": approval.reason,
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "timestamp": time.time(),
        },
    )
    if approval.decision == "reject" and approval.decided_by == "system":
        return
    resolved = await approval_manager.wait_decision(approval.id)
    approval.decision = resolved.decision
    approval.edited_args = resolved.edited_args
    approval.decided_by = resolved.decided_by


async def real_chat_stream(
    agent_runtime,
    message: str,
    session_id: str,
    thread_id: str,
    recursion_limit: int = 200,
) -> AsyncIterator[str]:
    agent = agent_runtime.agent
    metrics_queue: queue.Queue | None = getattr(agent_runtime, "metrics_queue", None)

    approved_tools: set[str] = set()
    rejected_tools: dict[str, str] = {}

    # metrics 桥接：线程队列 → asyncio 队列，用 call_soon_threadsafe
    metric_events: asyncio.Queue = asyncio.Queue(maxsize=2000)
    loop = asyncio.get_running_loop()

    # 把 loop 注册到 metrics_queue 的消费点（core 里的 _on_metric 会调用）
    try:
        agent_runtime.metrics_loop = loop
    except Exception:
        pass

    if metrics_queue is not None:
        # 用一个轻量 pump，只在收到线程通知时唤醒
        # 由于 core 里 _on_metric 是同步的，我们改造下：
        # 让 _on_metric 通过 call_soon_threadsafe 投递（见 core 里注释）
        # 这里提供一个兜底 drain，防止事件堆积
        async def _drain_loop():
            while True:
                try:
                    while True:
                        m = metrics_queue.get_nowait()
                        metric_events.put_nowait(m)
                except queue.Empty:
                    pass
                except Exception:
                    pass
                await asyncio.sleep(0.1)

        drain_task = asyncio.create_task(_drain_loop())
    else:
        drain_task = None

    try:
        agent_iter = agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": recursion_limit,
            },
            version="v2",
        ).__aiter__()

        agent_exhausted = False

        while not agent_exhausted or not metric_events.empty():
            # 1. 优先吐 metrics
            try:
                m = metric_events.get_nowait()
                yield sse("metrics", m)
                continue
            except asyncio.QueueEmpty:
                pass

            # 2. 拿 agent 事件（短超时，保证 metrics 及时）
            if not agent_exhausted:
                try:
                    event = await asyncio.wait_for(agent_iter.__anext__(), timeout=0.05)
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    agent_exhausted = True
                    continue

                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk is None:
                        continue
                    content = getattr(chunk, "content", "")
                    if content:
                        yield sse(
                            "token",
                            {
                                "content": content,
                                "session_id": session_id,
                            },
                        )

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_call_id = _extract_tool_call_id(event)
                    args = _extract_tool_args(event)

                    if (
                        approval_manager.is_sensitive(tool_name)
                        and tool_call_id not in approved_tools
                    ):
                        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:8]}"
                        async for chunk in _maybe_request_approval(
                            session_id=session_id,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            args=args,
                            thread_id=thread_id,
                            checkpoint_id=checkpoint_id,
                        ):
                            yield chunk

                        history = await approval_manager.list_history(session_id, limit=1)
                        decision = "approve"
                        edited_args = None
                        if history and history[0]["tool_call_id"] == tool_call_id:
                            decision = history[0]["decision"]
                            edited_args = history[0]["edited_args"]

                        if decision == "reject":
                            reason = f"用户拒绝执行: {tool_name}"
                            rejected_tools[tool_call_id] = reason
                            yield sse(
                                "error",
                                {
                                    "source": "tool",
                                    "tool_name": tool_name,
                                    "message": reason,
                                },
                            )
                            continue
                        if edited_args:
                            args = edited_args
                        approved_tools.add(tool_call_id)

                    yield sse(
                        "tool_start",
                        {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "args": args,
                            "timestamp": time.time(),
                        },
                    )

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    tool_call_id = _extract_tool_call_id(event)
                    if tool_call_id in rejected_tools:
                        continue
                    output = event["data"].get("output", "")
                    output_str = str(output) if output is not None else ""
                    yield sse(
                        "tool_end",
                        {
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "output": _truncate(output_str),
                            "timestamp": time.time(),
                        },
                    )

                elif kind == "on_tool_error":
                    tool_name = event.get("name", "")
                    tool_call_id = _extract_tool_call_id(event)
                    if tool_call_id in rejected_tools:
                        continue
                    err = event["data"].get("error")
                    yield sse(
                        "error",
                        {
                            "source": "tool",
                            "tool_name": tool_name,
                            "message": str(err) if err else "unknown tool error",
                        },
                    )

                elif kind == "on_chain_error":
                    err = event["data"].get("error")
                    if err:
                        yield sse(
                            "error",
                            {
                                "source": "server",
                                "message": f"{type(err).__name__}: {err}",
                            },
                        )

    except asyncio.CancelledError:
        raise
    except Exception as e:
        yield sse(
            "error",
            {
                "source": "server",
                "message": f"{type(e).__name__}: {e}",
            },
        )
    finally:
        if drain_task is not None:
            drain_task.cancel()
        # 吐干净剩余 metrics
        try:
            while True:
                m = metric_events.get_nowait()
                yield sse("metrics", m)
        except asyncio.QueueEmpty:
            pass
        except Exception:
            pass
        yield sse("done", {"session_id": session_id})
