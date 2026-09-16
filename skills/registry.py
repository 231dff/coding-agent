"""Skill 注册表。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from skills.loader import Skill, load_skills_from_dir

USER_INVOKED_SECTION = "用户主动触发（模型不自动激活）"

CATEGORY_ORDER = [
    "实现与测试",
    "设计与研究",
    "评审与诊断",
    "工程配置",
    "文档与交接",
]


class SkillRegistry:
    def __init__(self, definitions_dir: str | Path | None = None):
        if definitions_dir is None:
            here = Path(__file__).resolve().parent
            definitions_dir = here / "definitions"

        self.definitions_dir = Path(definitions_dir)
        self._skills: dict[str, Skill] = {}
        self._load()

    def _load(self) -> None:
        skills = load_skills_from_dir(self.definitions_dir, recursive=True)
        for s in skills:
            self._skills[s.name] = s

    # ---------- 查询 ----------

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def visible_skills(self) -> list[Skill]:
        """会被展示在 Available Skills 里的 skill。"""
        return [s for s in self._skills.values() if not s.hidden]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def skills_by_category(self) -> dict[str, list[Skill]]:
        groups: dict[str, list[Skill]] = defaultdict(list)
        for s in self._skills.values():
            if s.hidden:
                continue
            if s.disable_model_invocation:
                continue
            groups[s.category].append(s)
        return dict(groups)

    def user_invoked_skills(self) -> list[Skill]:
        return sorted(
            [s for s in self._skills.values() if s.disable_model_invocation and not s.hidden],
            key=lambda s: s.name,
        )

    def stats(self) -> dict:
        visible = self.visible_skills()
        total = len(self._skills)
        user = sum(1 for s in visible if s.disable_model_invocation)
        return {
            "total": total,
            "visible": len(visible),
            "hidden": total - len(visible),
            "model_invoked": len(visible) - user,
            "user_invoked": user,
        }

    # ---------- 元数据提示词 ----------

    def metadata_prompt(self) -> str:
        lines: list[str] = []

        lines.append("## Available Skills")
        lines.append("")
        lines.append("你可以通过 `load_skill` 工具加载以下技能的完整内容。")
        lines.append("")
        lines.append("**加载规则**：")
        lines.append("- 当任务**命中触发条件**时，ALWAYS 先 `load_skill` 再执行。")
        lines.append("- 命中 `不触发` 条件时，NEVER 加载。")
        lines.append('- 一次任务可加载多个技能（例如"实现功能 + 写测试" → `tdd` + `implement`）。')
        lines.append("- 不确定用哪个时，先看用户的原话，找最接近的触发条件。")
        lines.append("")

        groups = self.skills_by_category()

        def _cat_key(cat: str) -> tuple[int, str]:
            if cat in CATEGORY_ORDER:
                return (CATEGORY_ORDER.index(cat), cat)
            return (len(CATEGORY_ORDER), cat)

        for cat in sorted(groups.keys(), key=_cat_key):
            skills = sorted(groups[cat], key=lambda s: s.name)
            if not skills:
                continue
            lines.append(f"### {cat}")
            lines.append("")
            for s in skills:
                desc = s.description or "(无描述)"
                lines.append(f"- **{s.name}**: {desc}")
            lines.append("")

        user_skills = self.user_invoked_skills()
        if user_skills:
            lines.append(f"### {USER_INVOKED_SECTION}")
            lines.append("")
            lines.append(
                "以下技能**只在用户输入 `/技能名` 时激活**。用户没敲 `/` 时，按普通任务处理。"
            )
            lines.append("")
            for s in user_skills:
                desc = s.description or "(无描述)"
                lines.append(f"- `/{s.name}`: {desc}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def iter_skill_contents(
    registry: SkillRegistry,
    names: Iterable[str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        s = registry.get(name)
        if s is not None:
            out[name] = s.load()
    return out
