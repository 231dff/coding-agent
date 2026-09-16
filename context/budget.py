"""Day 17: 工具结果预算控制。

核心策略：大体积工具输出不直接进上下文，而是落盘到沙箱，
上下文中只保留摘要预览 + 文件路径。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage


@dataclass
class BudgetConfig:
    """预算控制配置。"""
    # 触发落盘的 token 阈值（粗略：1 token ≈ 4 chars）
    token_threshold: int = 2000
    # 预览行数
    preview_lines: int = 10
    # 预览字符数上限
    preview_chars: int = 800
    # 落盘目录（相对于工作区）
    offload_dir: str = ".context_offload"
    # 替换决策冻结：同一 tool_call_id 不重复处理
    freeze_decisions: bool = True


@dataclass
class OffloadedResult:
    """已落盘的工具结果。"""
    tool_call_id: str
    file_path: str
    original_size: int
    preview: str
    timestamp: float = field(default_factory=time.time)


class ToolResultBudget:
    """工具结果预算控制器。

    工作方式：
    1. 监听工具调用返回
    2. 如果输出超过阈值，落盘到文件系统
    3. 返回摘要预览 + 文件路径引用
    4. 替换决策冻结，避免重复处理
    """

    def __init__(self, workspace: str | Path, config: BudgetConfig | None = None):
        self.workspace = Path(workspace).resolve()
        self.config = config or BudgetConfig()
        self.offload_dir = self.workspace / self.config.offload_dir
        self.offload_dir.mkdir(parents=True, exist_ok=True)

        # 已冻结的替换决策：tool_call_id -> OffloadedResult
        self._frozen: dict[str, OffloadedResult] = {}

    def process_tool_result(
        self, tool_call_id: str, content: str, tool_name: str = ""
    ) -> str:
        """处理工具结果。

        返回：原始内容（如果未超阈值）或摘要预览（如果已落盘）。
        """
        # 冻结检查
        if self.config.freeze_decisions and tool_call_id in self._frozen:
            offloaded = self._frozen[tool_call_id]
            return self._format_preview(offloaded)

        # 估算 token
        estimated_tokens = len(content) // 4

        if estimated_tokens <= self.config.token_threshold:
            return content

        # 落盘
        offloaded = self._offload(tool_call_id, content, tool_name)

        if self.config.freeze_decisions:
            self._frozen[tool_call_id] = offloaded

        return self._format_preview(offloaded)

    def _offload(
        self, tool_call_id: str, content: str, tool_name: str
    ) -> OffloadedResult:
        """将内容落盘。"""
        # 文件名：tool_name + 哈希前缀
        safe_name = tool_name.replace("/", "_") if tool_name else "tool"
        hash_suffix = hashlib.md5(tool_call_id.encode()).hexdigest()[:8]
        filename = f"{safe_name}_{hash_suffix}.txt"
        file_path = self.offload_dir / filename

        file_path.write_text(content, encoding="utf-8")

        # 生成预览
        lines = content.splitlines()
        preview_lines = lines[:self.config.preview_lines]
        preview = "\n".join(preview_lines)
        if len(preview) > self.config.preview_chars:
            preview = preview[:self.config.preview_chars] + "..."

        rel_path = str(file_path.relative_to(self.workspace))

        return OffloadedResult(
            tool_call_id=tool_call_id,
            file_path=rel_path,
            original_size=len(content),
            preview=preview,
        )

    def _format_preview(self, offloaded: OffloadedResult) -> str:
        """格式化预览文本。"""
        return (
            f"[工具输出已落盘]\n"
            f"文件: {offloaded.file_path}\n"
            f"原始大小: {offloaded.original_size} chars "
            f"(约 {offloaded.original_size // 4} tokens)\n"
            f"预览:\n{offloaded.preview}\n"
            f"...\n"
            f"完整内容可通过 read_file 读取: {offloaded.file_path}"
        )

    def stats(self) -> dict:
        """返回预算统计。"""
        return {
            "offloaded_count": len(self._frozen),
            "total_offloaded_bytes": sum(
                o.original_size for o in self._frozen.values()
            ),
            "offload_dir": str(self.offload_dir),
        }