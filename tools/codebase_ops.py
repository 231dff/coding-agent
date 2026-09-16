"""Day 6-10: 代码库理解工具集。统一注册入口。"""

from langchain.tools import BaseTool

from codebase.call_graph import CallGraph, create_call_tools
from codebase.dep_graph import DependencyGraph, create_dep_tools
from codebase.impact import ImpactAnalyzer, create_impact_tool
from codebase.indexer import CodeIndexer, create_search_tool
from codebase.parser import CodeParser
from codebase.repo_map import RepoMapBuilder, create_repo_map_tool


def build_codebase_tools(workspace: str) -> tuple[list[BaseTool], dict]:
    """构建代码库理解工具集。

    Returns:
        (tools, context) — tools 为 LangChain 工具列表，
        context 为共享的解析器/图实例字典。
    """
    # 1. 解析器
    parser = CodeParser(workspace)

    # 2. Repo Map
    repo_map_builder = RepoMapBuilder(parser)
    repo_map_tool = create_repo_map_tool(repo_map_builder)

    # 3. 向量索引
    indexer = CodeIndexer(parser, persist_dir=f"{workspace}/.code_index")
    search_tool = create_search_tool(indexer)

    # 4. 文件依赖图
    dep_graph = DependencyGraph(parser)
    dep_graph.build()
    dep_tools = create_dep_tools(dep_graph)

    # 5. 调用图
    call_graph = CallGraph(parser)
    call_graph.build()
    call_tools = create_call_tools(call_graph)

    # 6. 影响分析
    analyzer = ImpactAnalyzer(call_graph, dep_graph)
    impact_tool = create_impact_tool(analyzer)

    tools = [
        repo_map_tool,
        search_tool,
        *dep_tools,
        *call_tools,
        impact_tool,
    ]

    context = {
        "parser": parser,
        "repo_map_builder": repo_map_builder,
        "indexer": indexer,
        "dep_graph": dep_graph,
        "call_graph": call_graph,
        "impact_analyzer": analyzer,
    }

    return tools, context


# Level 1 扩展工具名
CODEBASE_TOOLS = [
    "repo_map",
    "semantic_search",
    "get_file_dependents",
    "get_file_dependencies",
    "find_circular_deps",
    "find_callers",
    "find_callees",
    "analyze_impact",
]
