"""Agent 状态栏中间件。

缓存友好设计：
- 状态栏内容未变时不重复注入新消息
- 同步 + 异步双实现
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from context.status_bar import AgentStatusBar


class StatusBarMiddleware(AgentMiddleware):
    """状态栏中间件。"""

    name: str = "StatusBarMiddleware"

    def __init__(self, status_bar: AgentStatusBar):
        super().__init__()
        self.bar = status_bar
        # 记录上次注入的状态栏内容
        self._last_injected_content: str = ""

    # ---------- 同步 ----------

    def modify_model_request(self, request, model):
        return self._inject_status(request)

    def wrap_tool_call(self, request, handler):
        return self._handle_tool_call(request, handler)

    # ---------- 异步 ----------

    async def amodify_model_request(self, request, model):
        return self._inject_status(request)

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        if not tool_call:
            return await handler(request)

        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        try:
            result = await handler(request)
            self.bar.record_tool_call(tool_name, args, success=True)
            self._maybe_update_env(result)
            return result
        except Exception:
            self.bar.record_tool_call(tool_name, args, success=False)
            raise

    # ---------- 内部实现 ----------

    def _inject_status(self, request):
        """注入状态栏。

        **缓存友好**：
        1. 状态栏内容未变时，不重复注入
        2. 已有一条状态栏时，只在其后追加新的（persistent 模式）
        """
        messages = list(request.messages or [])

        # 计算当前状态栏文本
        status_text = self.bar.render()

        # **关键优化**：内容未变则不注入
        if status_text == self._last_injected_content:
            request.messages = messages
            return request

        self._last_injected_content = status_text

        # persistent 模式：直接追加新状态栏
        if self.bar.mode == "persistent":
            messages.append(
                HumanMessage(
                    content=status_text,
                    additional_kwargs={"is_agent_status": True},
                )
            )
        else:
            # replace 模式：移除旧状态栏，追加新的（会破坏缓存，不推荐）
            messages = [
                m
                for m in messages
                if not (getattr(m, "additional_kwargs", {}) or {}).get("is_agent_status")
            ]
            messages.append(
                HumanMessage(
                    content=status_text,
                    additional_kwargs={"is_agent_status": True},
                )
            )

        request.messages = messages
        return request

    def _handle_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        if not tool_call:
            return handler(request)

        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        try:
            result = handler(request)
            self.bar.record_tool_call(tool_name, args, success=True)
            self._maybe_update_env(result)
            return result
        except Exception:
            self.bar.record_tool_call(tool_name, args, success=False)
            raise

    def _maybe_update_env(self, result: Any) -> None:
        text = str(result)
        if "cwd:" in text:
            for line in text.splitlines():
                if line.strip().startswith("cwd:"):
                    self.bar.update_cwd(line.split(":", 1)[1].strip())
                    break
