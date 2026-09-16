"""Day 25: MCP 测试。"""

import pytest

from mcp_client.client import MCPConfig, load_mcp_tools_sync


def test_empty_config():
    config = MCPConfig(servers={})
    tools = load_mcp_tools_sync(config)
    assert tools == []


@pytest.mark.integration
def test_load_git_server_tools(tmp_path):
    """需要 git_server.py 存在。"""
    config = MCPConfig(
        servers={
            "git": {
                "command": "python",
                "args": ["mcp_client/servers/git_server.py"],
                "transport": "stdio",
            }
        }
    )
    tools = load_mcp_tools_sync(config)
    names = [t.name for t in tools]
    assert "git_status" in names or "git_diff" in names
