"""文件操作工具：read_file / write_file / edit_file / grep_search / glob_files / ls_dir。

设计原则：
- 读大文件默认截断 + 行号 + offset 提示
- 同一文件同一区间的内容哈希缓存，避免重复读
- 兼容老接口：read_file 支持 start_line/end_line；
  write_file 覆盖前自动备份 .bak；ls_dir 目录带 / 后缀
- glob 用 os.walk + 剪枝，遍历时跳过忽略目录
- 向后兼容：保留 set_workspace 作为 bind 的别名
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from langchain.tools import tool

# 全局工作区
_WORKSPACE: str | None = None

# 读文件缓存
_READ_CACHE: dict[str, tuple[str, str]] = {}

_DEFAULT_READ_LIMIT = 500
_MAX_READ_LIMIT = 2000

# 默认忽略的目录名
_IGNORE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        "node_modules",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "dist",
        "build",
        "out",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".fleet",
        ".cache",
        "target",
        ".coding-agent",
        ".sandbox_outputs",
    }
)


# ============================================================
# 工作区绑定
# ============================================================


def bind(workspace) -> None:
    """由 agent/core.py 调用，绑定工作区。

    兼容 str / Path 两种类型。
    """
    global _WORKSPACE
    _WORKSPACE = str(workspace)


# 向后兼容：旧的函数名
set_workspace = bind


# ============================================================
# 内部辅助
# ============================================================


def _resolve(path: str) -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("file_ops 未绑定工作区")

    root = Path(_WORKSPACE).resolve()
    p = (root / path).resolve()

    try:
        p.relative_to(root)
    except ValueError:
        raise ValueError(f"路径越界: {path}")

    return p


def _display_path(p: Path) -> str:
    try:
        return str(p.relative_to(Path(_WORKSPACE).resolve()))
    except Exception:
        return str(p)


def _should_ignore(path: Path) -> bool:
    return bool(set(path.parts) & _IGNORE_DIR_NAMES)


def _render_with_lines(path: str, content: str, start: int, end: int) -> str:
    lines = content.splitlines()
    total = len(lines)

    start = max(1, start)
    end = min(total, end) if end > 0 else total

    sliced = lines[start - 1 : end]
    width = len(str(end))
    numbered = [f"{start + i:>{width}}  {line}" for i, line in enumerate(sliced)]

    header = f"[{path}] 行 {start}-{end} / 共 {total} 行"
    if end < total:
        header += f"（还有 {total - end} 行，可用 offset={end + 1} 继续读）"

    return header + "\n" + "\n".join(numbered)


def _glob_to_regex(pattern: str) -> re.Pattern:
    pattern = pattern.replace("\\", "/").lstrip("./")

    out: list[str] = []
    i = 0
    n = len(pattern)

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    out.append(".*")
                    i += 2
                    continue
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".+()|^$[]{}\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(re.escape(c))
            i += 1

    return re.compile("^" + "".join(out) + "$")


# ============================================================
# read_file
# ============================================================


@tool
def read_file(
    path: str,
    offset: int = 1,
    limit: int = _DEFAULT_READ_LIMIT,
    start_line: int = -1,
    end_line: int = -1,
) -> str:
    """读取文件内容，返回带行号的文本。

    使用建议：
    - 只读需要的行范围；不要一次读整个大文件。
    - 如果需要更多内容，用 offset 继续读，而不是重复读第一段。
    - 同一文件、同一区间、内容未变时，返回 [cached] 提示。

    Args:
        path: 相对项目根目录的文件路径。
        offset: 起始行号（1-based，默认 1）。
        limit: 最多读取行数（默认 500，最大 2000）。
        start_line: [兼容老接口] 起始行号（0-based）。若提供，映射到 offset。
        end_line: [兼容老接口] 结束行号（0-based，exclusive）。若提供，映射到 limit。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    # 兼容老接口：start_line / end_line 是 0-based，end_line 为 exclusive
    if start_line >= 0 or end_line >= 0:
        s = max(0, start_line) if start_line >= 0 else 0
        e = end_line if end_line >= 0 else 0
        offset = s + 1
        if e > s:
            limit = e - s
        else:
            limit = _DEFAULT_READ_LIMIT

    try:
        full_path = _resolve(path)
    except ValueError as e:
        return f"ERROR: {e}"

    if not full_path.is_file():
        return f"ERROR: 文件不存在: {path}"

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: 读取失败: {type(e).__name__}: {e}"

    limit = max(1, min(limit, _MAX_READ_LIMIT))
    end = offset + limit - 1

    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
    cache_key = f"{path}:{offset}:{limit}"
    cached = _READ_CACHE.get(cache_key)

    if cached and cached[0] == content_hash:
        return f"[cached] {cached[1]}"

    rendered = _render_with_lines(path, content, offset, end)
    _READ_CACHE[cache_key] = (content_hash, rendered)

    return rendered


# ============================================================
# write_file
# ============================================================


@tool
def write_file(path: str, content: str) -> str:
    """完全覆盖写入文件。如文件已存在，原有内容会备份到 .bak。

    使用建议：
    - 局部修改请用 `edit_file`。

    Args:
        path: 相对项目根目录的文件路径。
        content: 要写入的完整内容。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    try:
        full_path = _resolve(path)
    except ValueError as e:
        return f"ERROR: {e}"

    # 覆盖前备份
    if full_path.exists():
        try:
            backup = full_path.with_suffix(full_path.suffix + ".bak")
            backup.write_text(
                full_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
        except Exception:
            pass

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"ERROR: 写入失败: {type(e).__name__}: {e}"

    for k in list(_READ_CACHE.keys()):
        if k.startswith(f"{path}:"):
            _READ_CACHE.pop(k, None)

    return f"OK: 已写入 {path}（{len(content)} 字符）"


# ============================================================
# edit_file
# ============================================================


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """把文件里的一段文本替换为新文本。

    Args:
        path: 相对项目根目录的文件路径。
        old_string: 要被替换的原文（必须与文件内容完全一致）。
        new_string: 替换后的新文本。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    try:
        full_path = _resolve(path)
    except ValueError as e:
        return f"ERROR: {e}"

    if not full_path.is_file():
        return f"ERROR: 文件不存在: {path}"

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: 读取失败: {type(e).__name__}: {e}"

    count = content.count(old_string)
    if count == 0:
        return "ERROR: old_string 未在文件中找到"
    if count > 1:
        return f"ERROR: old_string 出现 {count} 次，不唯一。请提供更长的上下文以唯一定位。"

    new_content = content.replace(old_string, new_string, 1)

    try:
        full_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"ERROR: 写入失败: {type(e).__name__}: {e}"

    for k in list(_READ_CACHE.keys()):
        if k.startswith(f"{path}:"):
            _READ_CACHE.pop(k, None)

    return f"OK: 已修改 {path}"


# ============================================================
# grep_search
# ============================================================


@tool
def grep_search(
    pattern: str,
    path: str = ".",
    file_glob: str = "",
    max_results: int = 50,
) -> str:
    """在文件内容里搜索匹配行。

    Args:
        pattern: 正则表达式。
        path: 搜索范围（文件或目录，相对项目根目录）。
        file_glob: 只搜索匹配的文件名模式，如 "*.py"。
        max_results: 最多返回多少条匹配。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    try:
        root = Path(_WORKSPACE).resolve()
        search_path = (root / path).resolve()
        search_path.relative_to(root)
    except ValueError as e:
        return f"ERROR: 路径越界: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    if not search_path.exists():
        return f"ERROR: 路径不存在: {path}"

    cmd = ["rg", "--line-number", "--no-heading", "--color=never"]

    for name in _IGNORE_DIR_NAMES:
        cmd += ["--glob", f"!**/{name}/**"]

    if file_glob:
        cmd += ["--glob", file_glob]

    cmd += [pattern, str(search_path)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return _grep_python_fallback(pattern, search_path, file_glob, max_results)
    except subprocess.TimeoutExpired:
        return "ERROR: 搜索超时（15s）"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    if not lines:
        return f"未找到匹配: {pattern}"

    truncated = len(lines) > max_results
    shown = lines[:max_results]

    fixed = []
    for line in shown:
        try:
            fixed.append(line.replace(str(root) + os.sep, ""))
        except Exception:
            fixed.append(line)

    result = "\n".join(fixed)
    if truncated:
        result += f"\n... （共 {len(lines)} 条，已显示前 {max_results} 条）"
    return result


def _grep_python_fallback(
    pattern: str,
    search_path: Path,
    file_glob: str,
    max_results: int,
) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"ERROR: 正则无效: {e}"

    matches: list[str] = []
    root = Path(_WORKSPACE).resolve()

    if search_path.is_file():
        candidates_iter = [(str(search_path.parent), [], [search_path.name])]
    else:
        candidates_iter = os.walk(search_path)

    for dirpath, dirnames, filenames in candidates_iter:
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIR_NAMES and not d.startswith(".")]

        for fname in filenames:
            if fname.startswith("."):
                continue

            f = Path(dirpath) / fname
            if file_glob and not f.match(file_glob):
                continue

            try:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if regex.search(line):
                        rel = f.relative_to(root)
                        matches.append(f"{rel}:{i}: {line.strip()}")
                        if len(matches) >= max_results * 2:
                            break
            except Exception:
                continue

            if len(matches) >= max_results * 2:
                break

        if len(matches) >= max_results * 2:
            break

    if not matches:
        return f"未找到匹配: {pattern}"

    truncated = len(matches) > max_results
    result = "\n".join(matches[:max_results])
    if truncated:
        result += "\n... （结果已截断）"
    return result


# ============================================================
# glob_files
# ============================================================


@tool
def glob_files(pattern: str, max_results: int = 100) -> str:
    """按路径模式匹配文件，不读取文件内容。

    Args:
        pattern: glob 模式，如 "**/*.py" 或 "src/**/*.ts"。
        max_results: 最多返回多少条。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    root = Path(_WORKSPACE).resolve()

    try:
        regex = _glob_to_regex(pattern)
    except Exception as e:
        return f"ERROR: 无效的 glob 模式: {e}"

    matches: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIR_NAMES and not d.startswith(".")]

        dir_path = Path(dirpath)

        for fname in filenames:
            if fname.startswith("."):
                continue

            full = dir_path / fname
            try:
                rel = full.relative_to(root)
            except ValueError:
                continue

            rel_str = str(rel).replace(os.sep, "/")
            if regex.match(rel_str):
                matches.append(rel)

        if len(matches) >= max_results * 3:
            break

    if not matches:
        return f"未找到匹配: {pattern}"

    matches.sort()
    truncated = len(matches) > max_results
    shown = matches[:max_results]

    lines = [str(p).replace(os.sep, "/") for p in shown]
    result = "\n".join(lines)
    if truncated:
        result += f"\n... （共 {len(matches)} 个文件，已显示前 {max_results} 个）"
    return result


# ============================================================
# ls_dir
# ============================================================


@tool
def ls_dir(path: str = ".", show_hidden: bool = False) -> str:
    """列出目录内容。

    Args:
        path: 相对项目根目录的路径。
        show_hidden: 是否显示隐藏文件（以 . 开头）。
    """
    if _WORKSPACE is None:
        return "ERROR: 未绑定工作区"

    try:
        full_path = _resolve(path)
    except ValueError as e:
        return f"ERROR: {e}"

    if not full_path.exists():
        return f"ERROR: 路径不存在: {path}"
    if not full_path.is_dir():
        return f"ERROR: 不是目录: {path}"

    entries = []
    try:
        for entry in sorted(
            full_path.iterdir(),
            key=lambda p: (not p.is_dir(), p.name),
        ):
            if entry.is_dir() and entry.name in _IGNORE_DIR_NAMES:
                continue
            if not show_hidden and entry.name.startswith("."):
                continue
            # 目录加 / 后缀（兼容老接口）
            if entry.is_dir():
                entries.append(f"{entry.name}/")
            else:
                entries.append(entry.name)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    if not entries:
        return f"[空目录] {path}"

    return f"[{path}]\n" + "\n".join(entries)


# ============================================================
# 导出
# ============================================================

FILE_TOOLS = [
    "read_file",
    "write_file",
    "edit_file",
    "grep_search",
    "glob_files",
    "ls_dir",
]
