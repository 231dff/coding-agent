"""上下文装配。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@dataclass
class ContextLayers:
    system_prompt: str = ""
    tool_definitions: str = ""
    project_memory: str = ""
    conversation_summary: str = ""
    recent_messages: list[BaseMessage] = field(default_factory=list)
    current_context: str = ""

    _stable_prefix_cache: str | None = field(default=None, init=False)

    def stable_prefix(self) -> str:
        """返回稳定前缀的完整文本（带缓存）。"""
        if self._stable_prefix_cache is not None:
            return self._stable_prefix_cache

        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        if self.tool_definitions:
            parts.append(f"## Available Tools\n{self.tool_definitions}")
        if self.project_memory:
            parts.append(f"## Project Memory\n{self.project_memory}")
        self._stable_prefix_cache = "\n\n".join(parts)
        return self._stable_prefix_cache

    def invalidate_prefix(self) -> None:
        """清空稳定前缀缓存。

        外部如果直接修改 system_prompt / tool_definitions / project_memory
        字段，应调用本方法让缓存失效。
        """
        self._stable_prefix_cache = None

    def to_messages(self) -> list[BaseMessage]:
        """将分层上下文转换为消息列表。"""
        messages: list[BaseMessage] = []

        system_parts = [self.stable_prefix()]
        if self.conversation_summary:
            system_parts.append(f"## Conversation Summary\n{self.conversation_summary}")
        messages.append(SystemMessage(content="\n\n".join(system_parts)))

        messages.extend(self.recent_messages)

        if self.current_context:
            messages.append(HumanMessage(content=self.current_context))

        return messages


class ContextAssembler:
    """上下文装配器。"""

    def __init__(
        self,
        system_prompt: str,
        tool_definitions: str = "",
        project_memory: str = "",
    ):
        self.layers = ContextLayers(
            system_prompt=system_prompt,
            tool_definitions=tool_definitions,
            project_memory=project_memory,
        )
        self._prefix_hash = self._hash_prefix()

    def _hash_prefix(self) -> str:
        """计算稳定前缀的哈希。

        关键：每次都重新拼稳定前缀，不用缓存。
        因为外部可能直接改 layers.system_prompt 等字段，
        缓存会让我们误判"前缀没变"。
        """
        self.layers.invalidate_prefix()
        return hashlib.sha256(self.layers.stable_prefix().encode("utf-8")).hexdigest()[:16]

    def check_prefix_stability(self) -> bool:
        """检测稳定前缀是否被意外修改。"""
        current = self._hash_prefix()
        if current != self._prefix_hash:
            self._prefix_hash = current
            return False
        return True

    def update_summary(self, summary: str) -> None:
        self.layers.conversation_summary = summary

    def update_recent(self, messages: list[BaseMessage]) -> None:
        self.layers.recent_messages = messages

    def update_current(self, context: str) -> None:
        self.layers.current_context = context

    def assemble(self) -> list[BaseMessage]:
        return self.layers.to_messages()

    def stats(self) -> dict:
        return {
            "system_prompt_chars": len(self.layers.system_prompt),
            "tool_defs_chars": len(self.layers.tool_definitions),
            "project_memory_chars": len(self.layers.project_memory),
            "summary_chars": len(self.layers.conversation_summary),
            "recent_messages_count": len(self.layers.recent_messages),
            "current_context_chars": len(self.layers.current_context),
        }
