"""工具过滤中间件。

- core_tools 全局固定（覆盖文件读写的所有基础能力）
- active skills 缓存（load_skill 触发）
- searched_tools 缓存（search_tools 触发，让搜到的工具真正生效）
- 兼容老接口：保留 _extract_active_skills(messages)
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware

# ★ 核心工具：覆盖「读 → 改 → 写 → 跑」闭环所需的最小集
_DEFAULT_CORE_TOOLS = frozenset(
    {
        # 文件读
        "read_file",
        "grep_search",
        "glob_files",
        "ls_dir",
        # 文件写（必须保留 write_file，否则无法创建新文件）
        "edit_file",
        "write_file",
        # 执行
        "execute",
        # 工具发现
        "search_tools",
    }
)


@dataclass
class ToolFilterConfig:
    core_tools: frozenset[str] = _DEFAULT_CORE_TOOLS
    max_exposed: int = 20
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
        self._searched_tools: set[str] = set()

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
        """运行时：检测本轮 load_skill，更新技能缓存。"""
        tool_call = getattr(request, "tool_call", None)
        if not tool_call:
            return
        if tool_call.get("name") == "load_skill":
            name = (tool_call.get("args") or {}).get("skill_name")
            if name:
                self._active_skills.add(name)

    def _track_search_result(self, request, result) -> None:
        """解析 search_tools 的返回，把匹配到的工具名加入 searched_tools。

        search_tools 的返回格式：
            找到 N 个匹配工具:
            - tool_name: description
            - tool_name2: description
        """
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

    def _compute_active(self, request) -> set[str]:
        active = set(self.config.core_tools)
        for skill_name in self._active_skills:
            active.update(self.skill_tool_map.get(skill_name, []))
        active.update(self._searched_tools)

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
        """[兼容老接口] 从 messages 列表里提取 load_skill 的技能名。"""
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
