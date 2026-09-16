"""工具过滤中间件。

缓存友好设计：
- core_tools 全局固定，不随会话变化
- 过滤结果按字母序排序，保证工具定义块稳定
- max_exposed 放宽，避免频繁削减工具集
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage


# 全局固定的核心工具集
_DEFAULT_CORE_TOOLS = frozenset({
    "read_file",
    "write_file",
    "edit_file",
    "grep_search",
    "glob_files",
    "ls_dir",
    "execute",
    "sandbox_read",
    "sandbox_write",
    "sandbox_grep",
    "load_skill",
    "search_tools",
})


@dataclass
class ToolFilterConfig:
    """工具过滤配置。"""
    # 全程固定不变的基础工具（用 frozenset 防止意外修改）
    core_tools: frozenset[str] = _DEFAULT_CORE_TOOLS
    # 单轮最多暴露的工具数（放宽，避免频繁削减）
    max_exposed: int = 30
    enabled: bool = True


class ToolFilterMiddleware(AgentMiddleware):
    """工具过滤中间件。"""

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

    # ---------- 同步 ----------

    def wrap_model_call(self, request, handler):
        return self._filter_and_call(request, handler)

    # ---------- 异步 ----------

    async def awrap_model_call(self, request, handler):
        return await self._filter_and_call_async(request, handler)

    # ---------- 内部 ----------

    def _compute_active(self, request) -> set[str]:
        """计算当前应暴露的工具集。"""
        messages = (
            request.state.get("messages", [])
            if hasattr(request, "state")
            else []
        )
        active_skills = self._extract_active_skills(messages)

        active = set(self.config.core_tools)
        for skill_name in active_skills:
            active.update(self.skill_tool_map.get(skill_name, []))

        if len(active) > self.config.max_exposed:
            core = set(self.config.core_tools)
            extra = active - core
            allowed_extra = list(extra)[: self.config.max_exposed - len(core)]
            active = core | set(allowed_extra)

        return active

    def _filter_and_call(self, request, handler):
        if not self.config.enabled:
            return handler(request)

        active = self._compute_active(request)
        # **关键**：按字母序排序，保证工具定义块在所有请求中的顺序一致
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

    def _extract_active_skills(self, messages: list[BaseMessage]) -> set[str]:
        skills: set[str] = set()
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "load_skill":
                        name = tc.get("args", {}).get("skill_name")
                        if name:
                            skills.add(name)
        return skills


def create_tool_filter_middleware(
    all_tool_names: list[str],
    skill_tool_map: dict[str, list[str]] | None = None,
) -> ToolFilterMiddleware:
    return ToolFilterMiddleware(all_tool_names, skill_tool_map)