"""工具过滤中间件。

- core_tools 全局固定
- active skills 缓存（在 wrap_tool_call 里维护）
- 兼容老接口：保留 _extract_active_skills(messages)
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware

_DEFAULT_CORE_TOOLS = frozenset({
    "read_file",       # 读文件，最基础
    "edit_file",       # 改代码，最基础
    "grep_search",     # 定位代码
    "glob_files",      # 定位文件
    "search_tools",    # 发现其他工具
})

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
    ):
        super().__init__()
        self.all_tool_names = set(all_tool_names)
        self.skill_tool_map = skill_tool_map or {}
        self.config = config or ToolFilterConfig()
        self._active_skills: set[str] = set()

    # ---------- 中间件入口 ----------

    def wrap_model_call(self, request, handler):
        return self._filter_and_call(request, handler)

    def wrap_tool_call(self, request, handler):
        self._track_skill_load(request)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        return await self._filter_and_call_async(request, handler)

    async def awrap_tool_call(self, request, handler):
        self._track_skill_load(request)
        return await handler(request)

    # ---------- 内部 ----------

    def _track_skill_load(self, request) -> None:
        """运行时：检测本轮是否 load_skill，更新缓存。"""
        tool_call = getattr(request, "tool_call", None)
        if not tool_call:
            return
        if tool_call.get("name") == "load_skill":
            name = (tool_call.get("args") or {}).get("skill_name")
            if name:
                self._active_skills.add(name)

    def _compute_active(self, request) -> set[str]:
        active = set(self.config.core_tools)
        for skill_name in self._active_skills:
            active.update(self.skill_tool_map.get(skill_name, []))

        if len(active) > self.config.max_exposed:
            core = set(self.config.core_tools)
            extra = list(active - core)
            active = core | set(extra[: self.config.max_exposed - len(core)])

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
        """[兼容老接口] 从 messages 列表里提取 load_skill 的技能名。

        新代码请依赖 self._active_skills 缓存（在 wrap_tool_call 里维护）。
        这个方法保留给测试和旧调用方使用。
        """
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
) -> ToolFilterMiddleware:
    return ToolFilterMiddleware(all_tool_names, skill_tool_map)
