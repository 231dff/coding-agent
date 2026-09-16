"""Day 6: tree-sitter AST 解析器。

封装 tree-sitter 的 Language/Parser API（0.23+ 版本），
提供文件级和目录级的 AST 解析能力，支持增量解析。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# 语言加载（0.23+ API：Language 接收 language() 的返回值）
import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Query, QueryCursor, Tree

PY_LANGUAGE = Language(tspython.language())

# 查询文件路径
_QUERY_DIR = Path(__file__).parent.parent / "queries"
_PY_TAGS_QUERY: Query | None = None


def _get_py_query() -> Query:
    """延迟加载 Python tags 查询，避免模块导入时的文件 IO。"""
    global _PY_TAGS_QUERY
    if _PY_TAGS_QUERY is None:
        scm_path = _QUERY_DIR / "python_tags.scm"
        _PY_TAGS_QUERY = Query(PY_LANGUAGE, scm_path.read_text(encoding="utf-8"))
    return _PY_TAGS_QUERY


@dataclass
class ParsedFile:
    """单个文件的解析结果。"""

    path: str  # 相对路径
    source: bytes  # 原始字节
    tree: Tree  # AST
    language: str = "python"
    mtime: float = 0.0  # 用于增量解析
    symbols: list[Symbol] = field(default_factory=list)


@dataclass
class Symbol:
    """一个代码符号（函数/类/方法/常量）。"""

    name: str
    kind: str  # function / class / method / constant
    file: str  # 相对路径
    start_line: int  # 1-based
    end_line: int  # 1-based
    signature: str = ""  # 只含签名的文本


class CodeParser:
    """tree-sitter 解析器封装，带缓存与增量解析。"""

    # 默认忽略的目录
    IGNORE_DIRS = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".egg-info",
        ".idea",
        ".vscode",
    }

    def __init__(self, workspace: str | Path, extensions: set[str] | None = None):
        self.workspace = Path(workspace).resolve()
        self.extensions = extensions or {".py"}
        self._parsers: dict[str, Parser] = {}
        self._cache: dict[str, ParsedFile] = {}

    def _get_parser(self, language: str) -> Parser:
        """按语言获取 Parser 实例（复用）。"""
        if language not in self._parsers:
            if language == "python":
                self._parsers[language] = Parser(PY_LANGUAGE)
            else:
                raise ValueError(f"不支持的语言: {language}")
        return self._parsers[language]

    def _detect_language(self, path: Path) -> str | None:
        """从文件扩展名推断语言。"""
        ext_map = {".py": "python"}
        return ext_map.get(path.suffix)

    def iter_source_files(self) -> Iterator[Path]:
        """遍历工作区内所有源文件，跳过忽略目录。"""
        for root, dirs, files in os.walk(self.workspace):
            # 原地修改 dirs 以跳过忽略目录
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]
            for fname in files:
                p = Path(root) / fname
                if p.suffix in self.extensions:
                    yield p

    def parse_file(self, path: Path, force: bool = False) -> ParsedFile | None:
        """解析单个文件，带 mtime 缓存。

        如果文件未修改且已缓存，直接返回缓存结果。
        """
        abs_path = path.resolve()
        rel_path = str(abs_path.relative_to(self.workspace))
        mtime = abs_path.stat().st_mtime

        if not force and rel_path in self._cache:
            cached = self._cache[rel_path]
            if cached.mtime == mtime:
                return cached

        language = self._detect_language(path)
        if language is None:
            return None

        source = abs_path.read_bytes()
        parser = self._get_parser(language)
        tree = parser.parse(source)

        parsed = ParsedFile(
            path=rel_path,
            source=source,
            tree=tree,
            language=language,
            mtime=mtime,
        )
        parsed.symbols = self._extract_symbols(parsed)
        self._cache[rel_path] = parsed
        return parsed

    def _extract_symbols(self, parsed: ParsedFile) -> list[Symbol]:
        """用 tree-sitter query 从 AST 中提取符号。"""
        query = _get_py_query()
        cursor = QueryCursor(query)
        captures = cursor.captures(parsed.tree.root_node)

        symbols: list[Symbol] = []
        seen: set[tuple[str, int]] = set()

        for capture_name, nodes in captures.items():
            if not capture_name.startswith("definition."):
                continue
            kind = capture_name.split(".", 1)[1]
            for node in nodes:
                name = node.text.decode("utf-8")
                # 找到所在行
                start_line = node.start_point[0] + 1
                key = (name, start_line)
                if key in seen:
                    continue
                seen.add(key)

                # 向上找到完整的函数/类定义节点，以获取签名
                def_node = self._find_enclosing_definition(node, kind)
                if def_node is None:
                    continue

                end_line = def_node.end_point[0] + 1
                signature = self._extract_signature(def_node, parsed.source)

                symbols.append(
                    Symbol(
                        name=name,
                        kind=kind,
                        file=parsed.path,
                        start_line=start_line,
                        end_line=end_line,
                        signature=signature,
                    )
                )

        return symbols

    def _find_enclosing_definition(self, node: Node, kind: str) -> Node | None:
        """从标识符节点向上找到完整的定义节点。"""
        target_types = {
            "function": "function_definition",
            "class": "class_definition",
            "method": "function_definition",
            "constant": "assignment",
        }
        target = target_types.get(kind)
        if target is None:
            return None

        cur = node
        while cur is not None:
            if cur.type == target:
                return cur
            cur = cur.parent
        return None

    def _extract_signature(self, def_node: Node, source: bytes) -> str:
        """提取定义节点的签名（不含函数体）。"""
        # 找到函数体子节点，签名 = 定义开始到 body 之前
        body = def_node.child_by_field_name("body")
        if body is not None:
            sig_bytes = source[def_node.start_byte : body.start_byte]
        else:
            # 常量赋值等没有 body，取整行
            sig_bytes = source[def_node.start_byte : def_node.end_byte]

        sig = sig_bytes.decode("utf-8").strip()
        # 压缩多行签名为单行
        sig = " ".join(sig.split())
        # 去掉末尾的冒号或等号
        return sig.rstrip(":=").rstrip()

    def parse_all(self, force: bool = False) -> list[ParsedFile]:
        """解析工作区内所有源文件。"""
        results = []
        for path in self.iter_source_files():
            parsed = self.parse_file(path, force=force)
            if parsed is not None:
                results.append(parsed)
        return results

    def all_symbols(self) -> list[Symbol]:
        """获取所有已解析文件的符号。"""
        symbols = []
        for parsed in self._cache.values():
            symbols.extend(parsed.symbols)
        return symbols

    def clear_cache(self) -> None:
        self._cache.clear()
