"""Day 2: 核心文件工具集。所有工具遵循 5 段式描述规范。"""
import os
import glob as glob_mod
import fnmatch
import re
from pathlib import Path
from langchain.tools import tool

# 全局工作区根目录，由 registry 在初始化时注入
_WORKSPACE: Path | None = None


def set_workspace(root: str | Path) -> None:
    global _WORKSPACE
    _WORKSPACE = Path(root).resolve()


def _resolve(path: str) -> Path:
    """将相对路径解析到工作区，并做越界检查。"""
    if _WORKSPACE is None:
        raise RuntimeError("workspace 未初始化，请先调用 set_workspace()")
    p = (_WORKSPACE / path).resolve()
    if not str(p).startswith(str(_WORKSPACE)):
        raise PermissionError(f"路径越界: {path}")
    return p


@tool
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """读取工作区内的文件内容，支持行号范围。

    Args:
        path: 相对于工作区根目录的文件路径。
        start_line: 起始行号（从 0 开始）。0 表示从文件开头。
        end_line: 结束行号（不含）。0 表示读到文件末尾。
    """
    p = _resolve(path)
    if not p.is_file():
        return f"ERROR: 文件不存在: {path}"

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    total = len(lines)
    s = max(0, start_line) if start_line > 0 else 0
    e = min(total, end_line) if end_line > 0 else total

    # 大文件截断策略：超过 2000 行只返回前 2000 行 + 摘要
    if e - s > 2000:
        e = s + 2000
        suffix = f"\n... (truncated, {total} lines total, showing lines {s}-{e})"
    else:
        suffix = ""

    return "".join(lines[s:e]) + suffix


@tool
def write_file(path: str, content: str) -> str:
    """覆盖写入工作区内的文件。如果文件已存在，会先备份为 .bak。

    Args:
        path: 相对于工作区根目录的文件路径。
        content: 要写入的完整文件内容。
    """
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.exists():
        backup = p.with_suffix(p.suffix + ".bak")
        backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    p.write_text(content, encoding="utf-8")
    return f"OK: 已写入 {path} ({len(content)} chars)"


@tool
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """精确字符串替换编辑文件。这是修改已有文件的首选方式，优于 write_file。

    Args:
        path: 相对于工作区根目录的文件路径。
        old_string: 要被替换的精确原文（必须唯一，除非 replace_all=True）。
        new_string: 替换后的新文本。
        replace_all: 是否替换所有匹配项。默认 False（要求 old_string 唯一）。
    """
    p = _resolve(path)
    if not p.is_file():
        return f"ERROR: 文件不存在: {path}"

    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)

    if count == 0:
        return f"ERROR: 未找到匹配文本。请检查 old_string 是否与文件内容完全一致（含缩进）。"
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string 出现 {count} 次，不唯一。"
            f"请提供更多上下文使其唯一，或设置 replace_all=True。"
        )

    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(new_text, encoding="utf-8")
    return f"OK: 已编辑 {path} (替换 {count if replace_all else 1} 处)"


@tool
def glob_files(pattern: str) -> str:
    """按 glob 模式查找工作区内的文件路径。

    Args:
        pattern: glob 模式，如 "**/*.py"、"src/**/*.ts"。
    """
    if _WORKSPACE is None:
        raise RuntimeError("workspace 未初始化")
    matches = glob_mod.glob(str(_WORKSPACE / pattern), recursive=True)
    files = [os.path.relpath(m, _WORKSPACE) for m in matches if os.path.isfile(m)]
    if not files:
        return f"未找到匹配 {pattern} 的文件"
    return "\n".join(sorted(files)[:200])


@tool
def grep_search(pattern: str, path: str = ".", context_lines: int = 2) -> str:
    """在工作区文件中搜索正则模式，返回匹配行及上下文。

    Args:
        pattern: 正则表达式。
        path: 搜索起始路径（相对工作区）。
        context_lines: 每个匹配行前后显示的上下文行数。
    """
    root = _resolve(path)
    regex = re.compile(pattern)
    results: list[str] = []

    for f in root.rglob("*"):
        if not f.is_file() or f.suffix not in {".py", ".js", ".ts", ".md", ".toml", ".yaml", ".yml", ".json"}:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                rel = os.path.relpath(f, _WORKSPACE)
                ctx = [f"{rel}:{j+1}: {lines[j]}" for j in range(start, end)]
                results.append("\n".join(ctx))
                results.append("---")

    if not results:
        return f"未找到匹配 '{pattern}' 的内容"
    # 大结果截断：最多返回前 50 个匹配块
    if len(results) > 100:
        results = results[:100] + ["... (结果已截断，共 {len(results)} 行)"]
    return "\n".join(results)


@tool
def ls_dir(path: str = ".") -> str:
    """列出工作区内的目录结构。

    Args:
        path: 相对于工作区根目录的路径。
    """
    p = _resolve(path)
    if not p.is_dir():
        return f"ERROR: 不是目录: {path}"

    lines = []
    for item in sorted(p.iterdir()):
        rel = item.relative_to(_WORKSPACE)
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{rel}{suffix}")
    return "\n".join(lines) if lines else "(空目录)"