"""Day 10: 变更影响分析。

结合文件级依赖图和符号级调用图，计算修改某个符号的全部影响集。
用于编辑前的接口一致性检查。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codebase.call_graph import CallGraph
from codebase.dep_graph import DependencyGraph


@dataclass
class ImpactReport:
    """变更影响报告。"""

    symbol: str
    definition: list[tuple[str, str, int]] = field(default_factory=list)
    direct_callers: list[str] = field(default_factory=list)
    transitive_callers: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    total_impact: int = 0

    def to_text(self) -> str:
        """格式化为文本输出。"""
        lines = [f"# 变更影响分析: {self.symbol}", ""]

        if self.definition:
            lines.append("## 定义位置")
            for f, kind, line in self.definition:
                lines.append(f"  - {f}:{line} ({kind})")
            lines.append("")

        if self.direct_callers:
            lines.append(f"## 直接调用方 ({len(self.direct_callers)})")
            for c in self.direct_callers[:20]:
                lines.append(f"  - {c}")
            if len(self.direct_callers) > 20:
                lines.append(f"  ... 还有 {len(self.direct_callers) - 20} 个")
            lines.append("")

        if self.affected_files:
            lines.append(f"## 受影响的文件 ({len(self.affected_files)})")
            for f in sorted(self.affected_files):
                lines.append(f"  - {f}")
            lines.append("")

        lines.append(f"**总影响点: {self.total_impact}**")
        return "\n".join(lines)


class ImpactAnalyzer:
    """变更影响分析器。"""

    def __init__(
        self,
        call_graph: CallGraph,
        dep_graph: DependencyGraph,
    ):
        self.call_graph = call_graph
        self.dep_graph = dep_graph

    def analyze(self, symbol_name: str, max_depth: int = 3) -> ImpactReport:
        """分析修改指定符号的影响。

        Args:
            symbol_name: 符号名。
            max_depth: 传递调用方的追溯深度。
        """
        report = ImpactReport(symbol=symbol_name)

        # 1. 定义位置
        report.definition = self.call_graph.get_definition(symbol_name)
        if not report.definition:
            return report

        # 2. 直接调用方
        report.direct_callers = self.call_graph.callers_of(symbol_name)

        # 3. 传递调用方（BFS）
        transitive = set()
        frontier = set(report.direct_callers)
        visited = set(report.direct_callers)

        for _ in range(max_depth - 1):
            next_frontier = set()
            for caller in frontier:
                callers = self.call_graph.callers_of(caller)
                for c in callers:
                    if c not in visited:
                        visited.add(c)
                        next_frontier.add(c)
                        transitive.add(c)
            frontier = next_frontier
            if not frontier:
                break

        report.transitive_callers = sorted(transitive)

        # 4. 受影响的文件（去重）
        affected = set()
        # 定义所在文件
        for f, _, _ in report.definition:
            affected.add(f)
        # 调用方所在文件
        for c in report.direct_callers + report.transitive_callers:
            if "::" in c:
                affected.add(c.split("::")[0])

        report.affected_files = sorted(affected)
        report.total_impact = (
            len(report.definition) + len(report.direct_callers) + len(report.transitive_callers)
        )

        return report


# ---- LangChain 工具封装 ----


def create_impact_tool(analyzer: ImpactAnalyzer):
    """将 ImpactAnalyzer 封装为 LangChain 工具。"""
    from langchain.tools import tool

    @tool
    def analyze_impact(symbol_name: str, max_depth: int = 3) -> str:
        """分析修改指定函数/类的影响范围。

        在重命名、修改签名、删除函数之前，ALWAYS 使用此工具。
        返回受影响的文件和调用方列表。

        Args:
            symbol_name: 要分析的符号名。
            max_depth: 传递调用方追溯深度，默认 3。
        """
        report = analyzer.analyze(symbol_name, max_depth=max_depth)
        if not report.definition:
            return f"未找到符号 {symbol_name} 的定义"
        return report.to_text()

    return analyze_impact
