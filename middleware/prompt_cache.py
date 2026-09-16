"""提示缓存中间件。

缓存友好设计：
- OpenAI / Qwen / DeepSeek：设置 prompt_cache_key 让服务端识别会话前缀
- Anthropic：设置 cache_control 标记稳定前缀
- 同会话的 prompt_cache_key 稳定；跨会话不同
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware


class PromptCacheMiddleware(AgentMiddleware):
    """统一提示缓存中间件。"""

    name: str = "PromptCacheMiddleware"

    def __init__(
        self,
        cache_ttl: str = "5m",
        default_cache_key: str = "coding-agent-v1",
        enable_anthropic: bool = True,
        enable_openai: bool = True,
    ):
        super().__init__()
        self.cache_ttl = cache_ttl
        self.default_cache_key = default_cache_key
        self.enable_anthropic = enable_anthropic
        self.enable_openai = enable_openai

    # ---------- 同步 ----------

    def modify_model_request(self, request, model):
        return self._apply_cache(request, model)

    # ---------- 异步 ----------

    async def amodify_model_request(self, request, model):
        return self._apply_cache(request, model)

    # ---------- 内部 ----------

    def _apply_cache(self, request, model):
        provider = self._detect_provider(model)

        if provider == "anthropic" and self.enable_anthropic:
            return self._apply_anthropic_cache(request)
        elif provider == "openai" and self.enable_openai:
            return self._apply_openai_cache(request)

        return request

    def _detect_provider(self, model: Any) -> str:
        model_name = getattr(model, "model_name", "") or getattr(model, "model", "")
        name_lower = model_name.lower()
        if "claude" in name_lower:
            return "anthropic"
        if "gpt" in name_lower:
            return "openai"
        # Qwen / DeepSeek 走 OpenAI 兼容协议
        if "qwen" in name_lower or "deepseek" in name_lower:
            return "openai"
        return "unknown"

    def _apply_anthropic_cache(self, request):
        """Anthropic 用 cache_control 标记稳定前缀。"""
        model_settings = request.model_settings or {}
        model_settings["cache_control"] = {
            "type": "ephemeral",
            "ttl": self.cache_ttl,
        }
        request.model_settings = model_settings
        return request

    def _apply_openai_cache(self, request):
        """OpenAI 兼容接口设置 prompt_cache_key。

        关键点：
        - prompt_cache_key 是**顶层参数**，不是 model_settings 里的子参数
        - 用会话稳定值（thread_id），同一会话的所有请求共享缓存
        - 若没有 thread_id，用 default_cache_key 兜底
        """
        config = request.config or {}
        thread_id = config.get("configurable", {}).get("thread_id", "")

        # 用 thread_id 派生出稳定的 cache key
        cache_key = (
            f"{self.default_cache_key}-{thread_id}"
            if thread_id
            else self.default_cache_key
        )

        # 通过 override 传给底层模型
        # LangChain 1.0 的 ChatOpenAI 从 model_kwargs 里读取
        if hasattr(request, "model_kwargs"):
            existing = dict(request.model_kwargs or {})
            existing["prompt_cache_key"] = cache_key
            request.model_kwargs = existing
        else:
            # 兜底：塞到 model_settings，部分版本会透传
            model_settings = request.model_settings or {}
            model_settings["prompt_cache_key"] = cache_key
            request.model_settings = model_settings

        return request


def create_prompt_cache_middleware(
    cache_ttl: str = "5m",
    default_cache_key: str = "coding-agent-v1",
) -> PromptCacheMiddleware:
    return PromptCacheMiddleware(
        cache_ttl=cache_ttl,
        default_cache_key=default_cache_key,
    )