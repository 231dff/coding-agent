"""Day 15: Apply Patch 模式。

参考 OpenAI Apply Patch 格式，支持结构化的多文件 diff。
Agent 输出 patch 文本，集成层负责原子应用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PatchOp(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class PatchHunk:
    """一个文件修改块。"""

    path: str
    op: PatchOp
    new_content: str | None = None  # add
    hunks: list[tuple[list[str], list[str]]] = field(default_factory=list)  # update


@dataclass
class ParseError(Exception):
    """Patch 格式错误。"""

    message: str
    line_no: int = 0


class PatchParser:
    """解析 Apply Patch 格式的文本。

    格式示例：
        *** Begin Patch
        *** Add File: src/new.py
        +line 1
        +line 2
        *** Update File: src/old.py
        @@ def foo():
        -    return 1
        +    return 2
        *** Delete File: src/gone.py
        *** End Patch
    """

    BEGIN_RE = re.compile(r"^\*\*\*\s*Begin Patch\s*$")
    END_RE = re.compile(r"^\*\*\*\s*End Patch\s*$")
    ADD_RE = re.compile(r"^\*\*\*\s*Add File:\s*(.+?)\s*$")
    UPDATE_RE = re.compile(r"^\*\*\*\s*Update File:\s*(.+?)\s*$")
    DELETE_RE = re.compile(r"^\*\*\*\s*Delete File:\s*(.+?)\s*$")

    def parse(self, text: str) -> list[PatchHunk]:
        """解析 patch 文本为 PatchHunk 列表。"""
        lines = text.splitlines()
        if not lines:
            raise ParseError("空的 patch 文本")

        # 找到 Begin/End 标记
        begin_idx = end_idx = None
        for i, line in enumerate(lines):
            if self.BEGIN_RE.match(line):
                begin_idx = i
            elif self.END_RE.match(line):
                end_idx = i
                break

        if begin_idx is None:
            raise ParseError("缺少 '*** Begin Patch' 标记")
        if end_idx is None:
            raise ParseError("缺少 '*** End Patch' 标记")

        body = lines[begin_idx + 1 : end_idx]

        # 分段解析
        hunks: list[PatchHunk] = []
        i = 0
        while i < len(body):
            line = body[i]

            m = self.ADD_RE.match(line)
            if m:
                hunk, i = self._parse_add(body, i, m.group(1))
                hunks.append(hunk)
                continue

            m = self.UPDATE_RE.match(line)
            if m:
                hunk, i = self._parse_update(body, i, m.group(1))
                hunks.append(hunk)
                continue

            m = self.DELETE_RE.match(line)
            if m:
                hunks.append(PatchHunk(path=m.group(1), op=PatchOp.DELETE))
                i += 1
                continue

            if line.strip():
                raise ParseError(f"意外的行: {line}", i + 1)
            i += 1

        return hunks

    def _parse_add(self, body: list[str], idx: int, path: str) -> tuple[PatchHunk, int]:
        """解析 Add File 块。"""
        lines: list[str] = []
        i = idx + 1
        while i < len(body):
            line = body[i]
            if line.startswith("***") or (line and not line.startswith("+")):
                break
            if line.startswith("+"):
                lines.append(line[1:])
            i += 1
        return PatchHunk(path=path, op=PatchOp.ADD, new_content="\n".join(lines) + "\n"), i

    def _parse_update(self, body: list[str], idx: int, path: str) -> tuple[PatchHunk, int]:
        """解析 Update File 块。

        每个 @@ 开启一个 hunk，包含 - 和 + 行（以及上下文行）。
        """
        hunks: list[tuple[list[str], list[str]]] = []
        i = idx + 1
        old_lines: list[str] = []
        new_lines: list[str] = []
        in_hunk = False

        while i < len(body):
            line = body[i]

            if line.startswith("***"):
                break

            if line.startswith("@@"):
                # 上一个 hunk 结束
                if in_hunk and (old_lines or new_lines):
                    hunks.append((list(old_lines), list(new_lines)))
                old_lines, new_lines = [], []
                in_hunk = True
                i += 1
                continue

            if not in_hunk:
                i += 1
                continue

            if line.startswith("-"):
                old_lines.append(line[1:])
            elif line.startswith("+"):
                new_lines.append(line[1:])
            elif line.startswith(" "):
                # 上下文行，同时保留
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif not line.strip():
                # 空行也算上下文（有些格式用空行）
                old_lines.append("")
                new_lines.append("")
            i += 1

        if in_hunk and (old_lines or new_lines):
            hunks.append((list(old_lines), list(new_lines)))

        return PatchHunk(path=path, op=PatchOp.UPDATE, hunks=hunks), i


class PatchApplier:
    """将 PatchHunk 应用到工作区。"""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def apply(self, hunks: list[PatchHunk], check: bool = True) -> tuple[bool, list[str]]:
        """应用所有 hunk。

        Args:
            hunks: 解析后的 hunk 列表。
            check: 是否做预检查（不写盘，先验证所有 hunk 都能应用）。

        Returns:
            (success, messages)
        """
        messages: list[str] = []

        if check:
            ok, errors = self._precheck(hunks)
            if not ok:
                return False, errors
            messages.append("预检查通过")

        # 按顺序应用，任何失败则回滚
        applied: list[tuple[str, str | None]] = []  # (path, original_content)
        try:
            for hunk in hunks:
                original = self._snapshot(hunk.path)
                applied.append((hunk.path, original))
                self._apply_one(hunk)
                messages.append(f"已应用: {hunk.op.value} {hunk.path}")
        except Exception as e:
            # 回滚
            for path, original in reversed(applied):
                self._restore(path, original)
            return False, [f"应用失败: {e}", "已回滚所有修改"]

        return True, messages

    def _precheck(self, hunks: list[PatchHunk]) -> tuple[bool, list[str]]:
        """预检查：不写盘，验证每个 hunk 是否可应用。"""
        errors: list[str] = []
        for hunk in hunks:
            path = self.workspace / hunk.path
            if hunk.op == PatchOp.ADD:
                if path.exists():
                    errors.append(f"{hunk.path}: 文件已存在，无法 Add")
            elif hunk.op == PatchOp.UPDATE:
                if not path.is_file():
                    errors.append(f"{hunk.path}: 文件不存在")
                    continue
                content = path.read_text(encoding="utf-8")
                for i, (old_lines, _) in enumerate(hunk.hunks, 1):
                    old_text = "\n".join(old_lines)
                    if old_text and old_text not in content:
                        errors.append(f"{hunk.path} hunk {i}: 找不到匹配的旧文本")
            elif hunk.op == PatchOp.DELETE:
                if not path.is_file():
                    errors.append(f"{hunk.path}: 文件不存在")
        return len(errors) == 0, errors

    def _apply_one(self, hunk: PatchHunk) -> None:
        """应用单个 hunk。"""
        path = self.workspace / hunk.path

        if hunk.op == PatchOp.ADD:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(hunk.new_content or "", encoding="utf-8")

        elif hunk.op == PatchOp.DELETE:
            path.unlink()

        elif hunk.op == PatchOp.UPDATE:
            content = path.read_text(encoding="utf-8")
            for old_lines, new_lines in hunk.hunks:
                old_text = "\n".join(old_lines)
                new_text = "\n".join(new_lines)
                if old_text not in content:
                    raise ValueError(f"{hunk.path}: 找不到匹配: {old_text[:50]}...")
                content = content.replace(old_text, new_text, 1)
            path.write_text(content, encoding="utf-8")

    def _snapshot(self, path: str) -> str | None:
        """拍摄文件快照，用于回滚。"""
        p = self.workspace / path
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8")

    def _restore(self, path: str, original: str | None) -> None:
        """从快照恢复。"""
        p = self.workspace / path
        if original is None:
            # 原文件不存在，删除
            if p.is_file():
                p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(original, encoding="utf-8")


# ---- LangChain 工具封装 ----


def create_apply_patch_tool(workspace: str):
    """创建 apply_patch 工具。"""
    from langchain.tools import tool

    parser = PatchParser()
    applier = PatchApplier(workspace)

    @tool
    def apply_patch(patch_text: str) -> str:
        """应用结构化的多文件补丁。

        格式：
        *** Begin Patch
        *** Update File: path/to/file.py
        @@ context marker
        -old line
        +new line
        *** Add File: path/new.py
        +new content
        *** Delete File: path/gone.py
        *** End Patch

        当需要同时修改多个文件时，ALWAYS 优先使用此工具，
        而非多次调用 edit_file。

        Args:
            patch_text: 完整的 patch 文本（含 Begin/End 标记）。
        """
        try:
            hunks = parser.parse(patch_text)
        except ParseError as e:
            return f"ERROR: patch 格式错误 (行 {e.line_no}): {e.message}"

        if not hunks:
            return "ERROR: patch 中没有任何文件操作"

        ok, messages = applier.apply(hunks, check=True)
        prefix = "OK" if ok else "ERROR"
        return f"{prefix}:\n" + "\n".join(f"  {m}" for m in messages)

    return apply_patch
