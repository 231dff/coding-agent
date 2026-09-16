"""Day 18: API 层微压缩 (L3)。

通过 Provider API 的上下文编辑能力，指示服务端从前缀中移除
指定的工具结果。零本地实现成本，但移除点之后的缓存会失效。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage


@dataclass
class APICompactionConfig:
    """API 微压缩配置。"""
    # 触发阈值：上下文占模型窗口的百分比
    trigger_fraction: float = 0.80
    # 要移除的工具结果数量（从最早的开始）
    remove_count: int = 5
    # 是否启用
    enabled: bool = True
    # 支持的 provider
    supported_providers: set[str] = field(
        default_factory=lambda: {"anthropic", "openai"}
    )


class APICompactor:
    """API 层微压缩器。

    工作原理：
    1. 检测上下文是否超过阈值
    2. 选择要移除的旧工具结果
    3. 通过 API 的上下文编辑参数指示服务端移除
    4. 本地消息保持不变

    注意：移除点之后的 KV Cache 会失效，需要重建。
    这是"零本地实现成本"的代价。
    """

    def __init__(self, config: APICompactionConfig | None = None):
        self.config = config or APICompactionConfig()

    def should_compact(
        self, current_tokens: int, model_window: int
    ) -> bool:
        """判断是否需要触发 API 微压缩。"""
        if not self.config.enabled:
            return False
        return (current_tokens / model_window) >= self.config.trigger_fraction

    def select_removals(
        self, messages: list[BaseMessage]
    ) -> list[str]:
        """选择要移除的 tool_call_id 列表。

        策略：从最早的、体积最大的工具结果开始移除。
        """
        from langchain_core.messages import ToolMessage

        candidates = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                size = len(str(msg.content))
                if size > 200:  # 只考虑有实质内容的
                    candidates.append((i, size, msg.tool_call_id))

        # 按大小降序、位置升序
        candidates.sort(key=lambda x: (-x[1], x[0]))
        selected = [c[2] for c in candidates[:self.config.remove_count]]
        return selected

    def build_api_params(
        self, provider: str, tool_call_ids: list[str]
    ) -> dict:
        """构建 API 参数。

        不同 provider 的上下文编辑参数格式不同。
        """
        if provider not in self.config.supported_providers:
            return {}

        if provider == "anthropic":
            # Anthropic 的 context editing 参数
            return {
                "context_editing": {
                    "type": "clear_tool_uses",
                    "tool_use_ids": tool_call_ids,
                }
            }
        elif provider == "openai":
            # OpenAI 的实现方式（具体参数名待确认）
            return {
                "context_editing": {
                    "type": "remove_messages",
                    "tool_call_ids": tool_call_ids,
                }
            }
        return {}