"""提示缓存中间件。

关键改动：
- 按传入的 model_provider 判断，不靠模型名猜
- Anthropic 把 cache_control 加到 system message 上
- OpenAI 兼容接口只保证前缀稳定，prompt_cache_key 在 build_llm 里已设
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage


class PromptCacheMiddleware(AgentMiddleware):
    name: str = "PromptCacheMiddleware"

    def __init__(
        self,
        cache_ttl: str = "5m",
        default_cache_key: str = "coding-agent-v1",
        model_provider: str = "openai",
        enable_anthropic: bool = True,
        enable_openai: bool = True,
    ):
        super().__init__()
        self.cache_ttl = cache_ttl
        self.default_cache_key = default_cache_key
        self.model_provider = model_provider
        self.enable_anthropic = enable_anthropic
        self.enable_openai = enable_openai

    def modify_model_request(self, request, model):
        return self._apply_cache(request, model)

    async def amodify_model_request(self, request, model):
        return self._apply_cache(request, model)

    def _apply_cache(self, request, model):
        if self.model_provider == "anthropic" and self.enable_anthropic:
            return self._apply_anthropic_cache(request)
        if self.model_provider == "openai" and self.enable_openai:
            return self._apply_openai_cache(request)
        return request

    def _apply_anthropic_cache(self, request):
        """在 system 消息上加 cache_control。"""
        messages = list(request.messages or [])
        if not messages:
            return request

        for i, msg in enumerate(messages):
            if isinstance(msg, SystemMessage):
                ak = dict(getattr(msg, "additional_kwargs", {}) or {})
                ak["cache_control"] = {
                    "type": "ephemeral",
                    "ttl": self.cache_ttl,
                }
                messages[i] = msg.model_copy(update={"additional_kwargs": ak})
                break

        request.messages = messages
        return request

    def _apply_openai_cache(self, request):
        """OpenAI 兼容接口：只确保前缀稳定，不运行时改 model_kwargs。"""
        return request


def create_prompt_cache_middleware(
    cache_ttl: str = "5m",
    default_cache_key: str = "coding-agent-v1",
    model_provider: str = "openai",
) -> PromptCacheMiddleware:
    return PromptCacheMiddleware(
        cache_ttl=cache_ttl,
        default_cache_key=default_cache_key,
        model_provider=model_provider,
    )
