"""Day 10: 符号级调用图。

从 AST 中提取函数调用关系，构建符号粒度的有向图。
用于精确的变更影响分析和接口一致性检查。
"""
from __future__ import annotations
from tree_sitter import QueryCursor
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx

from codebase.parser import CodeParser, ParsedFile


@dataclass
class CallEdge:
    """一条函数调用边。"""
    caller: str          # "file::func_name"
    callee: str          # "file::func_name" 或裸函数名
    file: str
    line: int


class CallGraph:
    """符号级调用图。"""

    def __init__(self, parser: CodeParser):
        self.parser = parser
        self.graph = nx.DiGraph()
        # 符号定义索引：symbol_name -> [(file, kind, start_line)]
        self._def_index: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        self._edges: list[CallEdge] = []

    def build(self) -> None:
        """构建调用图。"""
        parsed_files = self.parser.parse_all()

        # 第一遍：建立符号定义索引
        for pf in parsed_files:
            for sym in pf.symbols:
                self._def_index[sym.name].append(
                    (sym.file, sym.kind, sym.start_line)
                )
                # 节点 = 文件::符号
                node_id = f"{sym.file}::{sym.name}"
                self.graph.add_node(
                    node_id,
                    file=sym.file,
                    kind=sym.kind,
                    start_line=sym.start_line,
                )

        # 第二遍：提取调用关系
        from tree_sitter import QueryCursor
        from codebase.parser import _get_py_query

        query = _get_py_query()
        for pf in parsed_files:
            self._extract_calls(pf, query)

    def _extract_calls(self, parsed: ParsedFile, query) -> None:
        """从文件中提取函数调用。"""
        cursor = QueryCursor(query)
        captures = cursor.captures(parsed.tree.root_node)

        # 收集所有调用节点
        call_nodes = []
        for capture_name, nodes in captures.items():
            if capture_name == "reference.call":
                call_nodes.extend(nodes)

        # 找到每个调用所在的函数上下文
        for call_node in call_nodes:
            callee_name = call_node.text.decode("utf-8")
            if "." in callee_name:
                callee_name = callee_name.split(".")[-1]

            # 向上找到包含此调用的函数定义
            caller_sym = self._find_enclosing_function(call_node, parsed)
            if caller_sym is None:
                continue

            caller_id = f"{parsed.path}::{caller_sym.name}"

            # 解析 callee 到定义文件
            resolved = self._resolve_callee(callee_name, parsed.path)
            if resolved is None:
                continue

            callee_id = f"{resolved[0]}::{callee_name}"
            line = call_node.start_point[0] + 1

            self._edges.append(CallEdge(
                caller=caller_id,
                callee=callee_id,
                file=parsed.path,
                line=line,
            ))
            self.graph.add_edge(caller_id, callee_id)

    def _find_enclosing_function(self, node, parsed) -> object | None:
        """找到包含指定节点的函数定义。"""
        cur = node
        while cur is not None:
            if cur.type == "function_definition":
                name_node = cur.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode("utf-8")
                    # 在符号表中找到对应符号
                    for sym in parsed.symbols:
                        if sym.name == name and sym.kind in ("function", "method"):
                            return sym
            cur = cur.parent
        return None

    def _resolve_callee(
        self, name: str, current_file: str
    ) -> tuple[str, str, int] | None:
        """将函数名解析到定义位置。

        优先当前文件，然后全局索引。
        """
        candidates = self._def_index.get(name, [])
        if not candidates:
            return None
        # 优先当前文件
        for c in candidates:
            if c[0] == current_file:
                return c
        return candidates[0]

    # ---- 查询 API ----

    def callers_of(self, symbol: str) -> list[str]:
        """查询调用指定符号的所有符号。"""
        # 支持 "file::name" 或裸 "name"
        targets = self._match_nodes(symbol)
        result = set()
        for target in targets:
            if target in self.graph:
                result.update(self.graph.predecessors(target))
        return sorted(result)

    def callees_of(self, symbol: str) -> list[str]:
        """查询指定符号调用的所有符号。"""
        targets = self._match_nodes(symbol)
        result = set()
        for target in targets:
            if target in self.graph:
                result.update(self.graph.neighbors(target))
        return sorted(result)

    def _match_nodes(self, symbol: str) -> list[str]:
        """匹配符号名到图节点。"""
        if "::" in symbol:
            return [symbol] if symbol in self.graph else []
        # 裸名匹配
        return [
            n for n in self.graph.nodes()
            if n.split("::")[-1] == symbol
        ]

    def get_definition(self, symbol: str) -> list[tuple[str, str, int]]:
        """返回符号的定义位置列表。"""
        return self._def_index.get(symbol, [])


# ---- LangChain 工具封装 ----

def create_call_tools(call_graph: CallGraph):
    """将 CallGraph 封装为 LangChain 工具。"""
    from langchain.tools import tool

    @tool
    def find_callers(symbol_name: str) -> str:
        """查找调用了指定函数的所有位置。

        在修改函数签名前使用此工具找到所有调用方。

        Args:
            symbol_name: 函数名，可以是裸名或 "file::name" 格式。
        """
        callers = call_graph.callers_of(symbol_name)
        if not callers:
            return f"没有找到调用 {symbol_name} 的符号"
        return f"调用 {symbol_name} 的符号:\n" + "\n".join(f"  - {c}" for c in callers)

    @tool
    def find_callees(symbol_name: str) -> str:
        """查找指定函数调用了哪些其他函数。

        Args:
            symbol_name: 函数名。
        """
        callees = call_graph.callees_of(symbol_name)
        if not callees:
            return f"{symbol_name} 没有调用其他符号"
        return f"{symbol_name} 调用的符号:\n" + "\n".join(f"  - {c}" for c in callees)

    return find_callers, find_callees