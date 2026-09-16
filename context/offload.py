"""Day 20: 上下文卸载。

所有信息不都放在消息中，而是存储到外部文件系统，
消息中只保留文件路径。信息根据上下文压力和任务状态，
从完整原文逐步降级为 JSONL、摘要，再降级为 metadata。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import BaseMessage


@dataclass
class OffloadConfig:
    """卸载配置。"""

    base_dir: str = ".context_offload"
    # 完整日志落盘
    save_full_log: bool = True
    # 对话中保留截断版
    truncated_chars: int = 500
    # JSONL 索引
    save_jsonl_index: bool = True


class ContextOffloader:
    """上下文卸载器。

    存储分离设计：
    - 完整日志落盘（可追溯）
    - 对话中只留截断版
    - 即使上下文被压缩，Agent 仍可通过文件系统工具回溯完整信息
    """

    def __init__(self, workspace: str | Path, config: OffloadConfig | None = None):
        self.workspace = Path(workspace).resolve()
        self.config = config or OffloadConfig()
        self.base_dir = self.workspace / self.config.base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def offload_messages(
        self,
        messages: list[BaseMessage],
        session_id: str = "default",
        label: str = "",
    ) -> str:
        """将完整消息历史落盘，返回文件路径。

        Returns:
            落盘文件的相对路径。
        """
        timestamp = int(time.time())
        filename = (
            f"{session_id}_{label}_{timestamp}.md" if label else f"{session_id}_{timestamp}.md"
        )
        file_path = self.base_dir / filename

        content = self._serialize_messages(messages)
        file_path.write_text(content, encoding="utf-8")

        # JSONL 索引
        if self.config.save_jsonl_index:
            self._append_index(session_id, filename, len(messages))

        return str(file_path.relative_to(self.workspace))

    def _serialize_messages(self, messages: list[BaseMessage]) -> str:
        """序列化消息为 markdown。"""
        lines = ["# 对话历史快照\n", f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for i, msg in enumerate(messages):
            role = msg.__class__.__name__.replace("Message", "")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            lines.append(f"## [{i}] {role}\n")
            lines.append(content)
            lines.append("\n---\n")
        return "\n".join(lines)

    def _append_index(self, session_id: str, filename: str, message_count: int) -> None:
        """追加 JSONL 索引。"""
        index_file = self.base_dir / "index.jsonl"
        entry = {
            "session_id": session_id,
            "filename": filename,
            "message_count": message_count,
            "timestamp": time.time(),
        }
        with open(index_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_truncated(self, content: str) -> str:
        """返回截断版内容。"""
        if len(content) <= self.config.truncated_chars:
            return content
        return (
            content[: self.config.truncated_chars]
            + f"\n... (truncated, {len(content)} chars total)"
        )

    def retrieve(self, file_path: str) -> str:
        """回溯完整内容。"""
        full_path = self.workspace / file_path
        if not full_path.is_file():
            return f"文件不存在: {file_path}"
        return full_path.read_text(encoding="utf-8")
