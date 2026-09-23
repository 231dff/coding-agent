"""Day 25: MCP 客户端封装。

统一管理多个 MCP Server 的连接和工具加载。

配置文件加载优先级（高 → 低）：
1. <project>/.coding-agent/mcp.json
2. ~/.coding-agent/mcp.json
3. 内置 git / web server（AGENT_MCP_INCLUDE_BUILTIN=true 时）

配置格式（兼容 Claude Desktop / Cursor / Cline）：
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "transport": "http",
      "headers": {"Authorization": "Bearer ${env:GITHUB_PAT}"}
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  },
  "autoExpose": ["filesystem"]
}

★ sync 兼容：
- MCP 工具默认 async-only，不能直接被 sync agent 调用
- load_mcp_tools_sync 会把它们包装成 sync-callable StructuredTool
- 内部用专用 event loop 线程跑 async 调用

★ 日志：
- 全部走 observability.logger.get_logger("mcp")
- INFO 级别写文件，屏幕默认不显示
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from observability.logger import get_logger

log = get_logger("mcp")


# ============================================================
# 数据类
# ============================================================


@dataclass
class MCPConfig:
    """MCP 配置。"""

    servers: dict[str, dict] = field(default_factory=dict)
    auto_expose: list[str] = field(default_factory=list)


# ============================================================
# 专用 event loop（跑 async MCP 调用）
# ============================================================


class _AsyncRunner:
    """常驻 event loop 线程，用于同步调用 async 函数。"""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-async-runner")
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro):
        """在当前线程同步等待 coroutine 结果。"""
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


_runner_lock = threading.Lock()
_runner: _AsyncRunner | None = None


def _get_async_runner() -> _AsyncRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = _AsyncRunner()
        return _runner


# ============================================================
# async → sync 工具包装
# ============================================================


def _wrap_tool_for_sync(tool) -> StructuredTool:
    """把 async-only MCP 工具包装成 sync-callable StructuredTool。"""
    has_sync = getattr(tool, "func", None) is not None
    if has_sync:
        return tool

    coro = getattr(tool, "coroutine", None)
    if coro is None:
        return tool

    runner = _get_async_runner()
    tool_name = tool.name

    def _sync_invoke(**kwargs):
        return runner.run(tool.ainvoke(kwargs))

    try:
        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=getattr(tool, "args_schema", None),
            func=_sync_invoke,
            coroutine=coro,
            return_direct=getattr(tool, "return_direct", False),
            metadata=getattr(tool, "metadata", None),
            tags=getattr(tool, "tags", None),
        )
    except Exception as e:
        log.warning("wrap_tool_failed", tool=tool_name, error=str(e))
        return tool


# ============================================================
# 环境变量替换
# ============================================================

_ENV_PATTERN = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute_env(value):
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    return value


# ============================================================
# 配置文件加载
# ============================================================


def _read_config_file(path: Path) -> tuple[dict, list[str]]:
    """读取单个 mcp.json，返回 (servers, auto_expose)。"""
    if not path.is_file():
        return {}, []

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log.warning("parse_config_failed", path=str(path), error=str(e))
        return {}, []

    if not isinstance(data, dict):
        return {}, []

    servers = data.get("mcpServers") if "mcpServers" in data else data
    if not isinstance(servers, dict):
        log.warning("config_format_invalid", path=str(path), reason="mcpServers 必须是字典")
        return {}, []

    auto_expose = data.get("autoExpose", [])
    if not isinstance(auto_expose, list):
        auto_expose = []

    return _substitute_env(servers), auto_expose


def _normalize_server(name: str, spec: dict) -> dict | None:
    """规范化单个 server 配置。"""
    if not isinstance(spec, dict):
        log.warning("skip_server", server=name, reason="配置不是字典")
        return None

    result: dict = {}

    if "command" in spec:
        result["command"] = spec["command"]
        result["args"] = spec.get("args", [])
        result.setdefault("transport", "stdio")
    elif "url" in spec:
        result["url"] = spec["url"]
        result.setdefault("transport", spec.get("transport", "http"))
    else:
        log.warning("skip_server", server=name, reason="必须提供 command 或 url")
        return None

    if "transport" in spec:
        result["transport"] = spec["transport"]

    if "env" in spec and isinstance(spec["env"], dict):
        merged_env = {**os.environ, **{k: str(v) for k, v in spec["env"].items()}}
        result["env"] = merged_env

    if "headers" in spec and isinstance(spec["headers"], dict):
        result["headers"] = spec["headers"]

    return result


def load_mcp_servers(
    project_path: str | Path | None = None,
    agent_home: str | Path | None = None,
    *,
    include_builtin: bool = False,
    verbose: bool = True,
) -> MCPConfig:
    """从全局 + 项目级配置文件加载 MCP 配置。"""
    merged_servers: dict[str, dict] = {}
    merged_auto: list[str] = []

    global_path = Path.home() / ".coding-agent" / "mcp.json"
    g_servers, g_auto = _read_config_file(global_path)
    if g_servers:
        log.info("loaded_global_config", path=str(global_path), count=len(g_servers))
        merged_servers.update(g_servers)
        merged_auto.extend(g_auto)

    if project_path:
        project_cfg = Path(project_path) / ".coding-agent" / "mcp.json"
        p_servers, p_auto = _read_config_file(project_cfg)
        if p_servers:
            log.info("loaded_project_config", path=str(project_cfg), count=len(p_servers))
            merged_servers.update(p_servers)
            merged_auto.extend(p_auto)

    if include_builtin and agent_home:
        servers_dir = Path(agent_home) / "mcp_client" / "servers"
        for name, script in (("git", "git_server.py"), ("web", "web_search_server.py")):
            path = servers_dir / script
            if path.is_file():
                merged_servers.setdefault(
                    name,
                    {
                        "command": "python",
                        "args": [str(path)],
                        "transport": "stdio",
                    },
                )

    result: dict[str, dict] = {}
    for name, spec in merged_servers.items():
        normalized = _normalize_server(name, spec)
        if normalized:
            result[name] = normalized

    if result:
        log.info(
            "mcp_servers_loaded",
            count=len(result),
            servers=list(result.keys()),
            auto_expose=merged_auto or None,
        )
    else:
        log.info("mcp_no_servers")

    return MCPConfig(servers=result, auto_expose=list(set(merged_auto)))


# ============================================================
# Manager
# ============================================================


class MCPManager:
    """MCP 连接管理器。"""

    def __init__(self, config: MCPConfig):
        self.config = config
        self._client: MultiServerMCPClient | None = None
        self._tools: list = []
        self._tool_to_server: dict[str, str] = {}

    async def connect(self) -> list:
        """连接所有 MCP Server，加载工具。"""
        if not self.config.servers:
            return []

        self._client = MultiServerMCPClient(self.config.servers)
        self._tools = await self._client.get_tools()
        self._tool_to_server = self._build_tool_server_map()
        return self._tools

    def _build_tool_server_map(self) -> dict[str, str]:
        """从加载好的工具推断每个工具属于哪个 server。"""
        mapping: dict[str, str] = {}
        server_names = set(self.config.servers.keys())

        for t in self._tools:
            name = t.name
            server = None

            meta = getattr(t, "metadata", None) or {}
            if isinstance(meta, dict):
                server = meta.get("server") or meta.get("server_name")
                if not server:
                    for k in ("mcp_server", "source"):
                        if meta.get(k):
                            server = meta[k]
                            break

            if not server:
                for s in server_names:
                    if name.startswith(f"{s}_") or name.startswith(f"mcp_{s}_"):
                        server = s
                        break

            if not server and name.startswith("mcp_"):
                rest = name[4:]
                for s in server_names:
                    if rest.startswith(s):
                        server = s
                        break

            if server:
                mapping[name] = server

        return mapping

    @property
    def tools(self) -> list:
        return self._tools

    @property
    def tool_to_server(self) -> dict[str, str]:
        return self._tool_to_server

    async def disconnect(self) -> None:
        self._client = None
        self._tools = []
        self._tool_to_server = {}


# ============================================================
# 同步入口
# ============================================================


def load_mcp_tools_sync(config: MCPConfig) -> tuple[list, dict[str, str]]:
    """同步加载 MCP 工具。

    ★ 返回的工具已经包装成 sync-callable。

    Returns:
        (tools, tool_to_server)
    """
    manager = MCPManager(config)
    raw_tools = asyncio.run(manager.connect())
    tool_to_server = manager.tool_to_server

    wrapped_tools: list = []
    wrapped_count = 0
    for t in raw_tools:
        wrapped = _wrap_tool_for_sync(t)
        if wrapped is not t:
            wrapped_count += 1
        wrapped_tools.append(wrapped)

    if wrapped_count > 0:
        log.info("wrapped_sync_tools", count=wrapped_count)

    return wrapped_tools, tool_to_server
