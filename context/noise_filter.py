"""Day 18: 噪声删除 (L2)。

低价值内容直接移除，不做摘要——对噪声做摘要只是在浪费 token。
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import BaseMessage, ToolMessage


@dataclass
class NoiseFilterConfig:
    """噪声过滤配置。"""

    # 未被后续引用的搜索结果保留轮数
    orphan_search_ttl: int = 3
    # 重复读取的文件内容（相同 path 的旧结果）
    dedupe_reads: bool = True
    # 空白/无效的工具结果直接删除
    drop_empty_results: bool = True
    # 连续失败的工具调用（相同工具连续失败 N 次）
    consecutive_failure_threshold: int = 3


class NoiseFilter:
    """噪声过滤器。

    识别并直接删除低价值内容，不做摘要。
    """

    def __init__(self, config: NoiseFilterConfig | None = None):
        self.config = config or NoiseFilterConfig()

    def filter(self, messages: list[BaseMessage]) -> tuple[list[BaseMessage], dict]:
        """过滤消息列表中的噪声。

        Returns:
            (filtered_messages, stats)
        """
        stats = {
            "orphan_searches_removed": 0,
            "duplicate_reads_removed": 0,
            "empty_results_removed": 0,
            "total_removed": 0,
        }

        filtered: list[BaseMessage] = []
        seen_read_paths: dict[str, int] = {}  # path -> last index

        for i, msg in enumerate(messages):
            # 1. 空工具结果
            if isinstance(msg, ToolMessage) and self._is_empty(msg):
                stats["empty_results_removed"] += 1
                stats["total_removed"] += 1
                continue

            # 2. 重复的文件读取
            if isinstance(msg, ToolMessage) and self.config.dedupe_reads:
                path = self._extract_read_path(msg)
                if path:
                    if path in seen_read_paths:
                        # 保留最新的，移除旧的
                        old_idx = seen_read_paths[path]
                        if old_idx < len(filtered):
                            filtered[old_idx] = self._mark_removed(filtered[old_idx])
                            stats["duplicate_reads_removed"] += 1
                            stats["total_removed"] += 1
                    seen_read_paths[path] = len(filtered)

            filtered.append(msg)

        return filtered, stats

    def _is_empty(self, msg: ToolMessage) -> bool:
        """判断工具结果是否为空/无意义。"""
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        stripped = content.strip()
        if not stripped:
            return True
        # 只有 "OK" 或类似短确认
        if len(stripped) < 5 and stripped.lower() in {"ok", "done", "success"}:
            return True
        return False

    def _extract_read_path(self, msg: ToolMessage) -> str | None:
        """从工具调用中提取文件路径。"""
        # 通过 tool_call_id 反查参数较复杂，简化处理：
        # 如果内容是文件内容且长度较大，视为读取结果
        if len(str(msg.content)) > 500:
            # 用内容前 50 字符做指纹
            return str(msg.content)[:50]
        return None

    def _mark_removed(self, msg: BaseMessage) -> BaseMessage:
        """将消息标记为已移除（替换为极简占位符）。"""
        return ToolMessage(
            content="[已移除: 重复内容]",
            tool_call_id=getattr(msg, "tool_call_id", ""),
        )
