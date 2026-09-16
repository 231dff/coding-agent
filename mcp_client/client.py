"""Day 25: MCP 客户端封装。

统一管理多个 MCP Server 的连接和工具加载。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from langchain_mcp_adapters.client import MultiServerMCPClient


@dataclass
class MCPConfig:
    """MCP 配置。"""

    servers: dict[str, dict] = field(default_factory=dict)
    # 示例：
    # {
    #     "git": {"command": "python", "args": ["mcp/servers/git_server.py"], "transport": "stdio"},
    #     "web": {"url": "http://localhost:8000/mcp", "transport": "http"},
    # }


class MCPManager:
    """MCP 连接管理器。"""

    def __init__(self, config: MCPConfig):
        self.config = config
        self._client: MultiServerMCPClient | None = None
        self._tools: list = []

    async def connect(self) -> list:
        """连接所有 MCP Server，加载工具。"""
        if not self.config.servers:
            return []

        self._client = MultiServerMCPClient(self.config.servers)
        self._tools = await self._client.get_tools()
        return self._tools

    async def disconnect(self) -> None:
        """断开连接。"""
        if self._client:
            # MultiServerMCPClient 没有显式 close 方法，
            # 连接由上下文管理器管理
            self._client = None
            self._tools = []

    @property
    def tools(self) -> list:
        return self._tools


def load_mcp_tools_sync(config: MCPConfig) -> list:
    """同步加载 MCP 工具（内部使用 asyncio.run）。"""
    manager = MCPManager(config)
    return asyncio.run(manager.connect())
