"""Day 21: load_skill 工具。

支持跨技能引用：
- mattpocock/skills 的技能里可能出现 "Call the Skill tool with 'xxx'"
- 工具会检测这种引用并在返回值里提示 Agent 继续加载
"""
from __future__ import annotations

import re

from langchain.tools import tool

from skills.registry import SkillRegistry


_REGISTRY: SkillRegistry | None = None


def bind(registry: SkillRegistry) -> None:
    global _REGISTRY
    _REGISTRY = registry


# 匹配跨技能引用的正则
_SKILL_REF_RE = re.compile(
    r'Call the Skill tool with ["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def create_load_skill_tool(registry: SkillRegistry):
    """创建 load_skill 工具。"""

    @tool
    def load_skill(skill_name: str) -> str:
        """加载指定技能的完整内容。

        技能提供领域知识、配置模式和最佳实践。
        当任务匹配某个技能的触发条件时，ALWAYS 先加载对应技能。

        技能之间可能互相引用。如果加载的内容里出现
        "Call the Skill tool with 'xxx'"，说明这个技能是
        轻量入口，实际逻辑在 'xxx' 技能里。你应该继续调用
        load_skill("xxx") 获取完整指导。

        Args:
            skill_name: 技能名称（见系统提示中的 Available Skills）。
        """
        skill = registry.get(skill_name)
        if skill is None:
            # 尝试模糊匹配
            available = ", ".join(
                s.name for s in registry.all_skills()
            )
            return (
                f"ERROR: 未知技能 '{skill_name}'。\n"
                f"可用技能: {available}"
            )

        content = skill.load()

        # ---------- 组装返回值 ----------
        header_parts = [f"# 技能: {skill.name}"]

        if skill.category:
            header_parts.append(f"分类: {skill.category}")

        if skill.trigger:
            header_parts.append(f"触发条件: {skill.trigger}")

        if skill.tools:
            header_parts.append(f"关联工具: {', '.join(skill.tools)}")

        header = "\n".join(header_parts) + "\n\n"

        # ---------- 检测跨技能引用 ----------
        refs = _SKILL_REF_RE.findall(content)
        # 去重，排除自身
        refs = list(dict.fromkeys(r for r in refs if r != skill.name))

        if refs:
            header += (
                "⚠️ **此技能引用了其他技能，请继续调用**：\n"
            )
            for ref in refs:
                header += f'  - `load_skill("{ref}")`\n'
            header += "\n"

        return header + content

    return load_skill