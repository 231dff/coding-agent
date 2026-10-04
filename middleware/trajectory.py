"""轨迹持久化中间件（异步写）。

LangChain 1.4 稳定的 hook：
  wrap_model_call  — 每次 LLM 调用前，记录最后一条消息
  wrap_tool_call   — 每次工具调用前后，记录 tool_call + tool_result
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware

from observability.trajectory_writer import TrajectoryWriter


class TrajectoryMiddleware(AgentMiddleware):
    name: str = "TrajectoryMiddleware"

    def __init__(self, writer: TrajectoryWriter):
        super().__init__()
        self.writer = writer
        self._last_message_fingerprint: str = ""

    # ---------- wrap_model_call（同步 + 异步）----------

    def wrap_model_call(self, request, handler):
        self._record_last_message(request)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        self._record_last_message(request)
        return await handler(request)

    # ---------- wrap_tool_call（同步 + 异步）----------

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None)
        if tool_call:
            self.writer.append(
                "tool_call",
                {
                    "name": tool_call.get("name", ""),
                    "args": _truncate_dict(tool_call.get("args", {})),
                },
            )
        try:
            result = handler(request)
            if tool_call:
                self.writer.append(
                    "tool_result",
                    {
                        "name": tool_call.get("name", ""),
                        "success": True,
                        "output": str(result)[:2000],
                    },
                )
            return result
        except Exception as e:
            if tool_call:
                self.writer.append(
                    "tool_result",
                    {
                        "name": tool_call.get("name", ""),
                        "success": False,
                        "error": str(e)[:500],
                    },
                )
            raise

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None)
        if tool_call:
            self.writer.append(
                "tool_call",
                {
                    "name": tool_call.get("name", ""),
                    "args": _truncate_dict(tool_call.get("args", {})),
                },
            )
        try:
            result = await handler(request)
            if tool_call:
                self.writer.append(
                    "tool_result",
                    {
                        "name": tool_call.get("name", ""),
                        "success": True,
                        "output": str(result)[:2000],
                    },
                )
            return result
        except Exception as e:
            if tool_call:
                self.writer.append(
                    "tool_result",
                    {
                        "name": tool_call.get("name", ""),
                        "success": False,
                        "error": str(e)[:500],
                    },
                )
            raise

    # ---------- 内部 ----------

    def _record_last_message(self, request) -> None:
        messages = getattr(request, "messages", None) or []
        if not messages:
            return
        last = messages[-1]
        role = last.__class__.__name__.replace("Message", "").lower()
        content = last.content if isinstance(last.content, str) else str(last.content)
        fingerprint = f"{role}:{len(content)}:{content[:64]}"
        if fingerprint != self._last_message_fingerprint:
            self._last_message_fingerprint = fingerprint
            self.writer.append(
                "message",
                {
                    "role": role,
                    "content": content[:4000],
                },
            )

    def close(self) -> None:
        self.writer.close()


def _truncate_dict(d: dict, max_str: int = 500) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) > max_str:
            out[k] = v[:max_str] + "..."
        else:
            out[k] = v
    return out
