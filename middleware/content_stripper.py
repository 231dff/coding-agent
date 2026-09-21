"""Content 剥离中间件。

问题：模型在每轮 tool_call 前都会输出"预告"content，
      下一轮看到历史里的预告，又从开头续写，导致复读。

解决：在每次 LLM 请求前，把历史消息里所有"带 tool_calls 的
      AIMessage"的 content 清空，模型看不到预告，就不会续写。

副作用：没有。清理后的历史对模型来说是"更干净"的上下文。

实现要点（LangChain 1.0 AgentMiddleware）：
- 用 wrap_model_call / awrap_model_call，不用 modify_model_request
  （后者不是标准 hook，框架会静默忽略）
- 用 request.override(messages=...) 生成新 request，不直接赋值
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage


class ContentStripperMiddleware(AgentMiddleware):
    """剥离工具调用前 AI 消息的 content。"""

    name: str = "ContentStripperMiddleware"

    def __init__(self, enabled: bool = True, debug: bool = False):
        super().__init__()
        self.enabled = enabled
        self.debug = debug

    # ---------- 同步 ----------

    def wrap_model_call(self, request, handler):
        request = self._strip(request)
        return handler(request)

    # ---------- 异步 ----------

    async def awrap_model_call(self, request, handler):
        request = self._strip(request)
        return await handler(request)

    # ---------- 内部 ----------

    def _strip(self, request):
        if not self.enabled:
            return request

        messages = list(request.messages or [])
        changed = False

        for i, msg in enumerate(messages):
            # 只处理 AIMessage
            if not isinstance(msg, AIMessage):
                continue

            # 只处理带 tool_calls 的（工具调用轮次）
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue

            # content 非空才处理
            content = getattr(msg, "content", "")
            if not content:
                continue

            # 拷贝一份，把 content 置空
            messages[i] = msg.model_copy(update={"content": ""})
            changed = True

            if self.debug:
                print(
                    f"[stripper] 清空 message[{i}] 的 content "
                    f"({len(content)} 字符, {len(tool_calls)} 个 tool_calls)"
                )

        if not changed:
            return request

        # ★ 关键：用 override 生成新 request
        return request.override(messages=messages)


def create_content_stripper_middleware(
    enabled: bool = True,
    debug: bool = False,
) -> ContentStripperMiddleware:
    return ContentStripperMiddleware(enabled=enabled, debug=debug)