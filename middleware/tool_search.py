"""Day 22: 工具搜索。

让 Agent 通过关键词搜索发现工具，而非一次性看到所有工具定义。
"""
from __future__ import annotations

import re

from langchain.tools import tool


def create_tool_search_tool(all_tools: list):
    """创建 search_tools 工具。

    Args:
        all_tools: 全量工具列表（LangChain BaseTool 对象）。
    """

    @tool
    def search_tools(query: str) -> str:
        """按关键词搜索可用工具。

        当需要的能力不在当前工具集中时，用此工具搜索。
        支持工具名和描述的模糊匹配。

        Args:
            query: 搜索关键词，如 "git"、"database"、"search"。
        """
        if not query.strip():
            return "ERROR: 搜索关键词不能为空"

        query_lower = query.lower()
        matches = []
        for t in all_tools:
            name = t.name.lower()
            desc = (t.description or "").lower()
            if query_lower in name or query_lower in desc:
                # 返回工具名 + 描述首行
                desc_first = (t.description or "").split("\n", 1)[0].strip()
                matches.append(f"- {t.name}: {desc_first}")

        if not matches:
            return f"未找到匹配 '{query}' 的工具"

        header = f"找到 {len(matches)} 个匹配工具:\n"
        hint = "\n提示: 使用这些工具后，它们会自动加入你的可用工具集。"
        return header + "\n".join(matches) + hint

    return search_tools