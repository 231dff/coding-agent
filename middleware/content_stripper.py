"""Content 剥离中间件。

问题：模型在每轮 tool_call 前都会输出"预告"content，
      下一轮看到历史里的预告，又从开头续写，导致复读。

解决：在每次 LLM 请求前，把历史消息里所有"带 tool_calls 的
      AIMessage"的 content 清空，模型看不到预告，就不会续写。

副作用：没有。清理后的历史对模型来说是"更干净"的上下文。
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage


class ContentStripperMiddleware(AgentMiddleware):
    """剥离工具调用前 AI 消息的 content。"""

    name: str = "ContentStripperMiddleware"

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled

    def modify_model_request(self, request, model):
        return self._strip(request)

    async def amodify_model_request(self, request, model):
        return self._strip(request)

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

        if changed:
            request.messages = messages

        return request


def create_content_stripper_middleware(enabled: bool = True) -> ContentStripperMiddleware:
    return ContentStripperMiddleware(enabled=enabled)
