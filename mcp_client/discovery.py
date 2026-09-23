"""MCP 渐进式披露：元工具。

提供两个工具给 Agent：
- mcp_list_servers()      列出所有 MCP server（不暴露具体工具）
- mcp_use_server(name)    启用某个 server 的所有工具（下一轮起可用）

设计意图：
- MCP 工具默认不暴露给 LLM，节省 token
- Agent 需要时主动"揭示"某个 server
- 用户配多少 MCP 都不爆上下文
"""

from __future__ import annotations

from langchain.tools import tool


def create_mcp_meta_tools(
    server_to_tools: dict[str, list[str]],
    on_use_server,  # callback: (server_name) -> None
) -> list:
    """创建 MCP 元工具。

    Args:
        server_to_tools: server 名 → 工具名列表
        on_use_server:   揭示 server 的回调

    Returns:
        [mcp_list_servers, mcp_use_server]
    """

    @tool
    def mcp_list_servers() -> str:
        """列出所有可用的 MCP server（外部服务）。

        用途：当你需要访问外部系统（GitHub、数据库、远程 API 等）时，
        先调用此工具查看有哪些 MCP server 可用，再用 mcp_use_server 启用。

        Returns:
            每个 server 的名字、工具数、工具名样例。
        """
        if not server_to_tools:
            return "当前没有任何 MCP server 配置。请用户在 .coding-agent/mcp.json 中添加。"

        lines = [f"共 {len(server_to_tools)} 个 MCP server：\n"]
        for name, tools in sorted(server_to_tools.items()):
            preview = ", ".join(tools[:5])
            more = f" … (共 {len(tools)} 个)" if len(tools) > 5 else ""
            lines.append(f"## {name}")
            lines.append(f"  工具数: {len(tools)}")
            lines.append(f"  工具名: {preview}{more}")
            lines.append("")

        lines.append('提示：用 `mcp_use_server("<name>")` 启用某个 server 的工具。')
        return "\n".join(lines)

    @tool
    def mcp_use_server(server_name: str) -> str:
        """启用指定 MCP server 的所有工具。

        启用后，该 server 的所有工具会在**下一轮**对话中可用。

        Args:
            server_name: server 名，比如 "github" / "filesystem"。

        Returns:
            成功/失败提示。
        """
        if server_name not in server_to_tools:
            available = ", ".join(server_to_tools.keys()) or "(无)"
            return f"ERROR: 未知 server '{server_name}'。\n可用: {available}"

        on_use_server(server_name)
        tools = server_to_tools[server_name]
        preview = ", ".join(tools[:10])
        more = f" … (共 {len(tools)} 个)" if len(tools) > 10 else ""
        return (
            f"✓ 已启用 server '{server_name}'（{len(tools)} 个工具）。\n"
            f"下一轮起可用: {preview}{more}"
        )

    return [mcp_list_servers, mcp_use_server]
