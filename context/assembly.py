"""Day 16: 上下文装配。

核心原则：稳定前缀在前，动态内容在后。
稳定前缀 = 系统提示 + 工具定义 + 项目记忆，这些内容跨请求不变，
最大化前缀缓存命中率。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage


@dataclass
class ContextLayers:
    """上下文分层结构。按缓存友好顺序排列。"""

    # L0: 稳定前缀（跨请求不变，KV Cache 热区）
    system_prompt: str = ""
    tool_definitions: str = ""         # 工具定义的序列化文本
    project_memory: str = ""           # AGENTS.md 等长期记忆

    # L1: 半稳定（会话内不变，跨会话可能变）
    conversation_summary: str = ""     # 归档摘要（Day 19 引入）

    # L2: 动态（每请求变化）
    recent_messages: list[BaseMessage] = field(default_factory=list)
    current_context: str = ""          # 文件内容、搜索结果等

    def stable_prefix(self) -> str:
        """返回稳定前缀的完整文本。

        这段文本跨请求完全不变，是 KV Cache 命中的核心。
        """
        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        if self.tool_definitions:
            parts.append(f"## Available Tools\n{self.tool_definitions}")
        if self.project_memory:
            parts.append(f"## Project Memory\n{self.project_memory}")
        return "\n\n".join(parts)

    def to_messages(self) -> list[BaseMessage]:
        """将分层上下文转换为消息列表。

        顺序固定：system → summary → recent → current。
        这个顺序在每轮请求中保持不变，保证前缀稳定性。
        """
        messages: list[BaseMessage] = []

        # 1. System message 包含稳定前缀 + 摘要
        system_parts = [self.stable_prefix()]
        if self.conversation_summary:
            system_parts.append(f"## Conversation Summary\n{self.conversation_summary}")
        messages.append(SystemMessage(content="\n\n".join(system_parts)))

        # 2. 最近消息
        messages.extend(self.recent_messages)

        # 3. 当前动态上下文
        if self.current_context:
            messages.append(HumanMessage(content=self.current_context))

        return messages


class ContextAssembler:
    """上下文装配器。

    职责：
    - 管理分层上下文的更新
    - 保证稳定前缀不变
    - 在压缩时只修改动态层
    """

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
        # 记录稳定前缀的哈希，用于检测意外变动
        self._prefix_hash = self._hash_prefix()

    def _hash_prefix(self) -> str:
        import hashlib
        return hashlib.sha256(
            self.layers.stable_prefix().encode("utf-8")
        ).hexdigest()[:16]

    def check_prefix_stability(self) -> bool:
        """检测稳定前缀是否被意外修改。

        如果前缀变了，缓存会完全失效。这个方法用于断言/监控。
        """
        current = self._hash_prefix()
        if current != self._prefix_hash:
            # 更新哈希，但记录警告
            self._prefix_hash = current
            return False
        return True

    def update_summary(self, summary: str) -> None:
        """更新会话摘要（半稳定层，不影响稳定前缀）。"""
        self.layers.conversation_summary = summary

    def update_recent(self, messages: list[BaseMessage]) -> None:
        """更新最近消息。"""
        self.layers.recent_messages = messages

    def update_current(self, context: str) -> None:
        """更新当前动态上下文。"""
        self.layers.current_context = context

    def assemble(self) -> list[BaseMessage]:
        """装配最终的消息列表。"""
        return self.layers.to_messages()

    def stats(self) -> dict:
        """返回各层的字符数。"""
        return {
            "system_prompt_chars": len(self.layers.system_prompt),
            "tool_defs_chars": len(self.layers.tool_definitions),
            "project_memory_chars": len(self.layers.project_memory),
            "summary_chars": len(self.layers.conversation_summary),
            "recent_messages_count": len(self.layers.recent_messages),
            "current_context_chars": len(self.layers.current_context),
        }