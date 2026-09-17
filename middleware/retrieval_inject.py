"""运行时按任务检索并注入历史会话（第 2 层记忆）。

设计：
- 读最后一条 user 消息作为 query
- 检索 top-K 相关历史会话
- 作为 HumanMessage 追加到消息列表末尾（不改 system prompt，KV Cache 友好）
"""

from __future__ import annotations

import os

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from memory.retriever import get_retriever


class RetrievalInjectMiddleware(AgentMiddleware):
    """按当前任务检索历史会话，注入上下文。"""

    name: str = "RetrievalInjectMiddleware"

    def __init__(
        self,
        enabled: bool = True,
        top_k: int = 3,
        min_score: float = 1.5,
    ):
        super().__init__()
        self.enabled = enabled
        self.top_k = top_k
        self.min_score = min_score
        # 防止同一会话里重复注入同一条
        self._injected_session_ids: set[str] = set()

    def modify_model_request(self, request, model):
        return self._inject(request)

    async def amodify_model_request(self, request, model):
        return self._inject(request)

    def _inject(self, request):
        if not self.enabled:
            return request

        # 只在第一轮注入（避免每轮都检索）
        if self._injected_session_ids:
            return request

        query = self._extract_last_user_text(request.messages)
        if not query or len(query) < 5:
            return request

        try:
            retriever = get_retriever()
            items = retriever.search(
                query=query,
                top_k=self.top_k,
                min_score=self.min_score,
                user_id=os.getenv("AGENT_USER_ID", "default"),
            )
        except Exception:
            return request

        if not items:
            return request

        # 渲染
        lines = ["<recall>", "相关历史会话：", ""]
        for item in items:
            if item.session_id in self._injected_session_ids:
                continue
            self._injected_session_ids.add(item.session_id)
            lines.append(f"[{item.task_type}] {item.summary}")
            lines.append("")
        lines.append("</recall>")

        if len(lines) <= 4:
            return request

        messages = list(request.messages or [])
        messages.append(HumanMessage(content="\n".join(lines)))
        request.messages = messages
        return request

    @staticmethod
    def _extract_last_user_text(messages) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
            if "human" in role or "user" in role:
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    return "".join(parts)
        return ""


def create_retrieval_inject_middleware(
    enabled: bool = True,
    top_k: int = 3,
) -> RetrievalInjectMiddleware:
    return RetrievalInjectMiddleware(enabled=enabled, top_k=top_k)
