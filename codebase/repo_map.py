"""Day 7: Repo Map 生成。

参考 aider 的 repo map 模式：tree-sitter 解析 + PageRank 排序 +
二分搜索适配 token 预算。repo map 模式通过 tree-sitter 解析源代码，
按 PageRank 对符号排序，然后二分搜索将结果适配到 agent 的 token 预算中。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx

from codebase.parser import CodeParser, Symbol


@dataclass
class RepoMapEntry:
    """Repo Map 中的一个条目。"""

    file: str
    symbol: Symbol
    score: float


class RepoMapBuilder:
    """构建 token 预算内的代码骨架地图。"""

    def __init__(self, parser: CodeParser):
        self.parser = parser

    def build(
        self,
        token_budget: int = 2048,
        chat_files: list[str] | None = None,
        mentioned_files: list[str] | None = None,
    ) -> str:
        """生成 repo map 文本。

        Args:
            token_budget: 最大 token 数。
            chat_files: 当前对话中涉及的文件（用于个性化 PageRank 种子）。
            mentioned_files: 用户显式提到的文件。

        Returns:
            按文件分组的符号签名文本。
        """
        parsed_files = self.parser.parse_all()
        if not parsed_files:
            return "(空仓库，无源文件)"

        # 1. 构建引用图
        graph = self._build_reference_graph(parsed_files)

        # 2. 个性化 PageRank
        personalization = self._build_personalization(
            graph, chat_files or [], mentioned_files or []
        )
        scores = nx.pagerank(graph, alpha=0.85, personalization=personalization)

        # 3. 按文件聚合符号，按分数排序
        entries = self._rank_symbols(parsed_files, scores)

        # 4. 二分搜索适配 token 预算
        text = self._fit_to_budget(entries, token_budget)
        return text

    def _build_reference_graph(self, parsed_files) -> nx.DiGraph:
        """构建文件级引用图。

        节点 = 文件，边 = 文件 A 中的符号引用了文件 B 中的符号。
        """
        G = nx.DiGraph()

        # 第一遍：收集所有符号定义
        def_index: dict[str, list[str]] = defaultdict(list)  # symbol_name -> [files]
        for pf in parsed_files:
            G.add_node(pf.path)
            for sym in pf.symbols:
                if sym.kind in ("function", "class", "method"):
                    def_index[sym.name].append(pf.path)

        # 第二遍：提取引用关系
        from tree_sitter import QueryCursor

        from codebase.parser import _get_py_query

        query = _get_py_query()
        for pf in parsed_files:
            cursor = QueryCursor(query)
            captures = cursor.captures(pf.tree.root_node)

            for capture_name, nodes in captures.items():
                if not capture_name.startswith("reference."):
                    continue
                for node in nodes:
                    ref_name = node.text.decode("utf-8")
                    # 解析属性调用 obj.method
                    if "." in ref_name:
                        ref_name = ref_name.split(".")[-1]
                    # 找到定义该符号的文件
                    for def_file in def_index.get(ref_name, []):
                        if def_file != pf.path:
                            G.add_edge(pf.path, def_file, weight=1)

        return G

    def _build_personalization(
        self,
        graph: nx.DiGraph,
        chat_files: list[str],
        mentioned_files: list[str],
    ) -> dict[str, float] | None:
        """构建个性化向量：对话中的文件权重更高。

        个性化 PageRank 以对话/锚点文件作为相关性种子。
        """
        if not chat_files and not mentioned_files:
            return None

        weights: dict[str, float] = {}
        # 对话文件权重 5.0
        for f in chat_files:
            if f in graph:
                weights[f] = 5.0
        # 用户提到的文件权重 3.0
        for f in mentioned_files:
            if f in graph:
                weights[f] = max(weights.get(f, 0), 3.0)

        if not weights:
            return None

        # 归一化
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}

    def _rank_symbols(self, parsed_files, scores: dict[str, float]) -> list[RepoMapEntry]:
        """按文件分数对符号排序。"""
        entries = []
        for pf in parsed_files:
            file_score = scores.get(pf.path, 0.0)
            # 文件内符号按行号排序，保持阅读顺序
            for sym in sorted(pf.symbols, key=lambda s: s.start_line):
                entries.append(
                    RepoMapEntry(
                        file=pf.path,
                        symbol=sym,
                        score=file_score,
                    )
                )
        # 按分数降序
        entries.sort(key=lambda e: -e.score)
        return entries

    def _fit_to_budget(self, entries: list[RepoMapEntry], token_budget: int) -> str:
        """二分搜索适配 token 预算。

        get_ranked_tags_map() 方法二分搜索适配 max_map_tokens 的最多 ranked tags，
        目标控制在预算的 15% 以内。
        """

        # 估算每个条目的 token 数（粗略：1 token ≈ 4 chars）
        def render(entry_list: list[RepoMapEntry]) -> str:
            lines: list[str] = []
            current_file = None
            for e in entry_list:
                if e.file != current_file:
                    lines.append(f"\n{e.file}:")
                    current_file = e.file
                lines.append(f"  {e.symbol.signature}")
            return "\n".join(lines).strip()

        def estimate_tokens(text: str) -> int:
            return math.ceil(len(text) / 4)

        # 二分搜索最大的可适配条目数
        lo, hi = 0, len(entries)
        best_text = ""
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = entries[:mid]
            text = render(candidate)
            if estimate_tokens(text) <= token_budget:
                best_text = text
                lo = mid
            else:
                hi = mid - 1

        if not best_text and entries:
            # 预算太小，至少给第一个
            best_text = render(entries[:1])

        return best_text or "(无符号)"


# ---- LangChain 工具封装 ----


def create_repo_map_tool(builder: RepoMapBuilder):
    """将 RepoMapBuilder 封装为 LangChain 工具。"""
    from langchain.tools import tool

    @tool
    def repo_map(token_budget: int = 2048, focus_files: str = "") -> str:
        """生成代码库结构地图，展示关键文件中的函数和类签名。

        这是理解代码库全局结构的首选工具，优于逐个读取文件。

        Args:
            token_budget: 返回内容的最大 token 数，默认 2048。
            focus_files: 逗号分隔的文件路径，用于提升相关文件的排名。
        """
        chat = [f.strip() for f in focus_files.split(",") if f.strip()]
        return builder.build(token_budget=token_budget, chat_files=chat)

    return repo_map
