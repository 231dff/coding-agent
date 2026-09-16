"""Day 25: Web 搜索 MCP Server。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WebSearch")


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> str:
    """搜索网页。

    Args:
        query: 搜索关键词。
        max_results: 最大结果数。
    """
    import httpx
    # 使用 DuckDuckGo 的免费 API
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=10,
        )
        data = resp.json()
        results = []
        if data.get("Abstract"):
            results.append(f"摘要: {data['Abstract']}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"- {topic['Text'][:200]}")
        return "\n".join(results) if results else "未找到结果"
    except Exception as e:
        return f"搜索失败: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")