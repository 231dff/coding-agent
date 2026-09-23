"""工具过滤中间件。

- core_tools 全局固定
- MCP 工具**默认不暴露**，按需通过 `mcp_use_server` 揭示
- active skills 缓存（load_skill 触发）
- searched_tools 缓存（search_tools 触发）
- 兼容老接口：保留 _extract_active_skills(messages)
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware

_DEFAULT_CORE_TOOLS = frozenset(
    {
        "read_file",
        "grep_search",
        "glob_files",
        "ls_dir",
        "edit_file",
        "write_file",
        "execute",
        "search_tools",
        # ★ MCP 元工具始终暴露
        "mcp_list_servers",
        "mcp_use_server",
    }
)


@dataclass
class ToolFilterConfig:
    core_tools: frozenset[str] = _DEFAULT_CORE_TOOLS
    max_exposed: int = 30
    enabled: bool = True


class ToolFilterMiddleware(AgentMiddleware):
    name: str = "ToolFilterMiddleware"

    def __init__(
        self,
        all_tool_names: list[str],
        skill_tool_map: dict[str, list[str]] | None = None,
        config: ToolFilterConfig | None = None,
        # ★ 新增：MCP server → 工具名列表
        mcp_server_to_tools: dict[str, list[str]] | None = None,
        # ★ 新增：启动时就暴露的 server
        auto_expose_servers: list[str] | None = None,
    ):
        super().__init__()
        self.all_tool_names = set(all_tool_names)
        self.skill_tool_map = skill_tool_map or {}
        self.config = config or ToolFilterConfig()

        self._active_skills: set[str] = set()
        self._searched_tools: set[str] = set()

        # ★ MCP 相关
        self._mcp_server_to_tools: dict[str, list[str]] = mcp_server_to_tools or {}
        self._exposed_mcp_servers: set[str] = set(auto_expose_servers or [])

    # ---------- 对外接口：被 mcp_use_server 元工具调用 ----------

    def expose_mcp_server(self, server_name: str) -> bool:
        """揭示一个 MCP server 的工具（下一轮起暴露）。"""
        if server_name not in self._mcp_server_to_tools:
            return False
        self._exposed_mcp_servers.add(server_name)
        return True

    # ---------- 中间件入口 ----------

    def wrap_model_call(self, request, handler):
        return self._filter_and_call(request, handler)

    def wrap_tool_call(self, request, handler):
        self._track_tool_calls(request)
        result = handler(request)
        self._track_search_result(request, result)
        return result

    async def awrap_model_call(self, request, handler):
        return await self._filter_and_call_async(request, handler)

    async def awrap_tool_call(self, request, handler):
        self._track_tool_calls(request)
        result = await handler(request)
        self._track_search_result(request, result)
        return result

    # ---------- 内部 ----------

    def _track_tool_calls(self, request) -> None:
        tool_call = getattr(request, "tool_call", None)
        if not tool_call:
            return
        if tool_call.get("name") == "load_skill":
            name = (tool_call.get("args") or {}).get("skill_name")
            if name:
                self._active_skills.add(name)

    def _track_search_result(self, request, result) -> None:
        tool_call = getattr(request, "tool_call", None)
        if not tool_call or tool_call.get("name") != "search_tools":
            return

        text = result if isinstance(result, str) else getattr(result, "content", str(result))

        for line in str(text).split("\n"):
            line = line.strip()
            if line.startswith("- "):
                rest = line[2:]
                if ":" in rest:
                    name = rest.split(":", 1)[0].strip()
                    if name in self.all_tool_names:
                        self._searched_tools.add(name)

    def _mcp_tools_to_expose(self) -> set[str]:
        """当前已揭示的 MCP 工具名集合。"""
        result: set[str] = set()
        for server in self._exposed_mcp_servers:
            result.update(self._mcp_server_to_tools.get(server, []))
        return result

    def _compute_active(self, request) -> set[str]:
        """计算本轮暴露的工具集。

        规则：
        1. core_tools（含 MCP 元工具）永远暴露
        2. 已激活 skill 的工具暴露
        3. search_tools 搜到的工具暴露
        4. ★ 只有"已揭示"的 MCP server 的工具才暴露
        5. 超出 max_exposed 时按字母序裁剪额外工具
        """
        core = set(self.config.core_tools)

        active = set(core)
        for skill_name in self._active_skills:
            active.update(self.skill_tool_map.get(skill_name, []))
        active.update(self._searched_tools)
        active.update(self._mcp_tools_to_expose())

        if len(active) > self.config.max_exposed:
            extra = sorted(active - core)
            budget = self.config.max_exposed - len(core)
            if budget > 0:
                active = core | set(extra[:budget])
            else:
                active = core

        return active

    def _filter_and_call(self, request, handler):
        if not self.config.enabled:
            return handler(request)

        active = self._compute_active(request)
        filtered = sorted(
            [t for t in request.tools if t.name in active],
            key=lambda t: t.name,
        )
        if not filtered:
            return handler(request)
        return handler(request.override(tools=filtered))

    async def _filter_and_call_async(self, request, handler):
        if not self.config.enabled:
            return await handler(request)

        active = self._compute_active(request)
        filtered = sorted(
            [t for t in request.tools if t.name in active],
            key=lambda t: t.name,
        )
        if not filtered:
            return await handler(request)
        return await handler(request.override(tools=filtered))

    # ---------- 兼容老接口 ----------

    def _extract_active_skills(self, messages) -> set[str]:
        skills: set[str] = set()
        for msg in messages or []:
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue
            for tc in tool_calls:
                name = None
                args = None
                if isinstance(tc, dict):
                    name = tc.get("name")
                    args = tc.get("args") or {}
                else:
                    name = getattr(tc, "name", None)
                    args = getattr(tc, "args", None) or {}
                if name == "load_skill":
                    skill_name = args.get("skill_name") if isinstance(args, dict) else None
                    if skill_name:
                        skills.add(skill_name)
        return skills


def create_tool_filter_middleware(
    all_tool_names: list[str],
    skill_tool_map: dict[str, list[str]] | None = None,
    mcp_server_to_tools: dict[str, list[str]] | None = None,
    auto_expose_servers: list[str] | None = None,
) -> ToolFilterMiddleware:
    return ToolFilterMiddleware(
        all_tool_names,
        skill_tool_map,
        mcp_server_to_tools=mcp_server_to_tools,
        auto_expose_servers=auto_expose_servers,
    )
