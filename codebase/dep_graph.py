"""Day 9: 文件级依赖图。

解析 Python 文件的 import 语句，构建文件到文件的依赖关系。
支持正向/反向查询、循环依赖检测、传递依赖分析。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from codebase.parser import CodeParser


@dataclass
class ImportInfo:
    """一条 import 记录。"""

    source_file: str
    target_module: str  # 原始模块字符串
    resolved_file: str | None  # 解析后的文件路径（None 表示外部包）
    line: int
    names: list[str]  # 导入的符号名


class DependencyGraph:
    """文件级依赖图，基于 import 解析。

    构建有向图：节点 = 文件，边 = A 导入 B。
    """

    def __init__(self, parser: CodeParser):
        self.parser = parser
        self.graph = nx.DiGraph()
        self.imports: list[ImportInfo] = []
        self._module_map: dict[str, str] = {}  # module_name -> file_path

    def build(self) -> None:
        """构建依赖图。"""
        parsed_files = self.parser.parse_all()

        # 第一遍：建立模块名到文件路径的映射
        self._build_module_map(parsed_files)

        # 第二遍：解析 import
        for pf in parsed_files:
            self.graph.add_node(pf.path)
            self._parse_imports(pf)

        # 添加边
        for imp in self.imports:
            if imp.resolved_file and imp.resolved_file != imp.source_file:
                self.graph.add_edge(
                    imp.source_file,
                    imp.resolved_file,
                    names=imp.names,
                    line=imp.line,
                )

    def _build_module_map(self, parsed_files) -> None:
        """建立 Python 模块名到文件路径的映射。

        处理规则：
        - src/foo/bar.py → foo.bar
        - src/foo/__init__.py → foo
        - foo.py → foo
        """
        for pf in parsed_files:
            path = Path(pf.path)
            # 去掉 .py 后缀
            parts = list(path.with_suffix("").parts)

            # 跳过常见的 src 前缀
            if parts and parts[0] in ("src", "lib"):
                parts = parts[1:]

            # 处理 __init__.py
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]

            if not parts:
                continue

            module_name = ".".join(parts)
            self._module_map[module_name] = pf.path

            # 也注册短名（最后一段）
            short = parts[-1]
            if short not in self._module_map:
                self._module_map[short] = pf.path

    def _parse_imports(self, parsed) -> None:
        """用 Python ast 解析 import 语句。

        使用标准库 ast 而非 tree-sitter，因为 import 解析需要
        精确的模块名处理，ast 的 API 更直接。
        """
        try:
            tree = ast.parse(parsed.source)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._record_import(
                        parsed.path, alias.name, None, node.lineno, [alias.asname or alias.name]
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                self._record_import(parsed.path, module, node.level, node.lineno, names)

    def _record_import(
        self,
        source_file: str,
        module: str,
        level: int | None,
        line: int,
        names: list[str],
    ) -> None:
        """记录一条 import 并尝试解析到文件。"""
        resolved = self._resolve_module(module, source_file)
        self.imports.append(
            ImportInfo(
                source_file=source_file,
                target_module=module,
                resolved_file=resolved,
                line=line,
                names=names,
            )
        )

    def _resolve_module(self, module: str, source_file: str) -> str | None:
        """将模块名解析到文件路径。"""
        if not module:
            return None

        # 尝试完整模块名
        if module in self._module_map:
            return self._module_map[module]

        # 尝试逐级截断
        parts = module.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in self._module_map:
                return self._module_map[candidate]
            parts.pop()

        # 尝试相对于当前文件解析
        source_dir = Path(source_file).parent
        for suffix in (".py", "/__init__.py"):
            candidate = str(source_dir / (module.replace(".", "/") + suffix))
            if candidate in self._module_map.values():
                return candidate

        return None

    # ---- 查询 API ----

    def dependents(self, file: str, depth: int = 1) -> list[str]:
        """查询依赖指定文件的文件（反向依赖）。

        Args:
            file: 目标文件路径。
            depth: 追溯深度。
        """
        if file not in self.graph:
            return []
        # 反向图中的 BFS
        rev = self.graph.reverse()
        visited = {file}
        frontier = [file]
        result = []
        for _ in range(depth):
            next_frontier = []
            for node in frontier:
                for neighbor in rev.neighbors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                        result.append(neighbor)
            frontier = next_frontier
        return result

    def dependencies(self, file: str, depth: int = 1) -> list[str]:
        """查询指定文件依赖的文件（正向依赖）。"""
        if file not in self.graph:
            return []
        visited = {file}
        frontier = [file]
        result = []
        for _ in range(depth):
            next_frontier = []
            for node in frontier:
                for neighbor in self.graph.neighbors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                        result.append(neighbor)
            frontier = next_frontier
        return result

    def find_cycles(self) -> list[list[str]]:
        """检测循环依赖。"""
        try:
            return list(nx.simple_cycles(self.graph))
        except Exception:
            return []

    def topological_order(self) -> list[str] | None:
        """拓扑排序（如果无循环依赖）。"""
        try:
            return list(nx.topological_sort(self.graph))
        except nx.NetworkXUnfeasible:
            return None

    def export_mermaid(self, max_nodes: int = 50) -> str:
        """导出 Mermaid 格式的依赖图（用于可视化）。"""
        lines = ["graph TD"]
        nodes = list(self.graph.nodes())[:max_nodes]
        node_set = set(nodes)
        for u, v in self.graph.edges():
            if u in node_set and v in node_set:
                # 简化节点名
                u_label = Path(u).stem
                v_label = Path(v).stem
                lines.append(f"    {u_label} --> {v_label}")
        return "\n".join(lines)


# ---- LangChain 工具封装 ----


def create_dep_tools(dep_graph: DependencyGraph):
    """将 DependencyGraph 封装为 LangChain 工具。"""
    from langchain.tools import tool

    @tool
    def get_file_dependents(file_path: str, depth: int = 1) -> str:
        """查询哪些文件依赖于指定文件。

        在修改文件前使用此工具评估影响范围。

        Args:
            file_path: 目标文件路径（相对于工作区）。
            depth: 追溯深度，默认 1（直接依赖）。
        """
        deps = dep_graph.dependents(file_path, depth=depth)
        if not deps:
            return f"没有文件依赖于 {file_path}"
        return f"依赖于 {file_path} 的文件（深度 {depth}）:\n" + "\n".join(f"  - {d}" for d in deps)

    @tool
    def get_file_dependencies(file_path: str, depth: int = 1) -> str:
        """查询指定文件依赖了哪些文件。

        Args:
            file_path: 目标文件路径。
            depth: 追溯深度，默认 1。
        """
        deps = dep_graph.dependencies(file_path, depth=depth)
        if not deps:
            return f"{file_path} 没有依赖其他文件"
        return f"{file_path} 依赖的文件（深度 {depth}）:\n" + "\n".join(f"  - {d}" for d in deps)

    @tool
    def find_circular_deps() -> str:
        """查找代码库中的循环依赖。"""
        cycles = dep_graph.find_cycles()
        if not cycles:
            return "未发现循环依赖"
        lines = [f"发现 {len(cycles)} 个循环依赖:"]
        for i, cycle in enumerate(cycles[:10], 1):
            lines.append(f"  {i}. {' → '.join(cycle)} → {cycle[0]}")
        return "\n".join(lines)

    return get_file_dependents, get_file_dependencies, find_circular_deps
