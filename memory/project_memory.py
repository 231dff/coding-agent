"""Day 26: 项目记忆 (AGENTS.md 风格)。

首次在项目目录运行时自动创建，跨会话积累项目知识。
强制条目简短、与行动相关、以约束表述。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TEMPLATE = """# Agent Project Memory

> 本文件由 Coding Agent 自动维护。跨会话积累的项目约定。
> 手工编辑请保持条目简短、可执行、以约束表述（ALWAYS / NEVER）。

## Build & Test
<!-- 常用命令，如: build, test, lint, format -->

## Conventions
<!-- 编码规范、命名约定、目录结构约定 -->

## Constraints
<!-- 禁止事项、危险操作、兼容性要求 -->

## Known Issues
<!-- 已知问题、坑、workaround -->
"""


@dataclass
class MemoryEntry:
    """一条记忆条目。"""

    section: str
    text: str
    source: str = "agent"  # agent | user
    created_at: float = field(default_factory=time.time)
    confidence: float = 1.0


class ProjectMemory:
    """项目记忆管理器。

    文件结构：
        # Agent Project Memory
        ## Build & Test
        - ALWAYS 用 uv 而非 pip
        ## Conventions
        - NEVER 用 print 调试，用 logger
    """

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / "AGENTS.md"

    def exists(self) -> bool:
        return self.path.is_file()

    def ensure_initialized(self) -> bool:
        """确保 AGENTS.md 存在。首次调用会创建模板。

        Returns:
            True 表示本次新创建了文件。
        """
        if self.path.exists():
            return False
        self.path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
        return True

    def load(self) -> str:
        """加载完整内容。"""
        if not self.path.is_file():
            return ""
        return self.path.read_text(encoding="utf-8")

    def add(self, section: str, text: str, source: str = "agent") -> bool:
        """添加一条记忆。

        去重规则：同一 section 下，文本相似度 > 0.9 视为重复。
        长度限制：单条 ≤ 200 字符。
        """
        if len(text) > 200:
            text = text[:197] + "..."

        text = text.strip()
        if not text:
            return False

        self.ensure_initialized()
        content = self.load()
        entries = self._parse(content)

        # 去重
        for e in entries:
            if e.section == section and self._similar(e.text, text):
                return False

        # 追加到对应 section
        new_content = self._insert_entry(content, section, text)
        self.path.write_text(new_content, encoding="utf-8")
        return True

    def remove(self, section: str, text: str) -> bool:
        """删除一条记忆。"""
        content = self.load()
        pattern = re.compile(
            rf"^-\s*{re.escape(text)}\s*$",
            re.MULTILINE,
        )
        new_content, n = pattern.subn("", content)
        if n == 0:
            return False
        self.path.write_text(new_content, encoding="utf-8")
        return True

    def _parse(self, content: str) -> list[MemoryEntry]:
        """解析现有条目。"""
        entries: list[MemoryEntry] = []
        current_section = ""
        for line in content.splitlines():
            if line.startswith("## "):
                current_section = line[3:].strip()
            elif line.startswith("- ") and current_section:
                entries.append(
                    MemoryEntry(
                        section=current_section,
                        text=line[2:].strip(),
                    )
                )
        return entries

    def _insert_entry(self, content: str, section: str, text: str) -> str:
        """将条目插入到指定 section 末尾。"""
        lines = content.splitlines()
        section_idx = None
        next_section_idx = None

        for i, line in enumerate(lines):
            if line.strip() == f"## {section}":
                section_idx = i
            elif section_idx is not None and line.startswith("## "):
                next_section_idx = i
                break

        if section_idx is None:
            # 新 section，追加到末尾
            lines.append("")
            lines.append(f"## {section}")
            lines.append(f"- {text}")
            return "\n".join(lines)

        insert_at = next_section_idx if next_section_idx else len(lines)

        # 跳过 section 末尾的空行
        while insert_at > section_idx + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1

        lines.insert(insert_at, f"- {text}")
        return "\n".join(lines)

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """简单相似度：Jaccard on words。"""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False
        inter = words_a & words_b
        union = words_a | words_b
        return len(inter) / len(union) > 0.9
