"""Day 21: 技能注册表。

技能 = 可复用的领域知识，按需加载。
元数据（名称+描述+触发条件）常驻系统提示，完整内容通过 load_skill 工具加载。

支持两种格式：
1. 本项目原生格式（name/description/trigger/tools）
2. mattpocock/skills 转换后的格式（name/description/trigger/category/disable_model_invocation）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    """一个技能。"""
    name: str
    description: str
    trigger: str = ""
    content: str = ""
    content_path: str = ""
    tools: list[str] = field(default_factory=list)
    # 新增字段（mattpocock 集成）
    category: str = ""
    disable_model_invocation: bool = False

    def load(self) -> str:
        """加载完整内容。"""
        if self.content:
            return self.content
        if self.content_path:
            p = Path(self.content_path)
            if p.is_file():
                self.content = p.read_text(encoding="utf-8")
                return self.content
        return f"(技能 {self.name} 无内容)"


class SkillRegistry:
    """技能注册表。

    扫描 skills/definitions/ 下的 markdown 文件，
    解析 frontmatter 生成 Skill 对象。
    """

    def __init__(self, definitions_dir: str | Path | None = None):
        if definitions_dir is None:
            definitions_dir = Path(__file__).parent / "definitions"
        self.definitions_dir = Path(definitions_dir)
        self._skills: dict[str, Skill] = {}
        self._load_all()

    # ---------- 加载 ----------

    def _load_all(self) -> None:
        """扫描目录，加载所有技能定义。"""
        if not self.definitions_dir.is_dir():
            return

        for md_file in sorted(self.definitions_dir.glob("*.md")):
            skill = self._parse_skill_file(md_file)
            if skill:
                self._skills[skill.name] = skill

    def _parse_skill_file(self, path: Path) -> Skill | None:
        """解析技能 markdown 文件。

        格式：
            ---
            name: xxx
            description: xxx
            trigger: xxx
            tools: a, b, c
            category: engineering
            disable_model_invocation: true
            ---
            # 完整内容...
        """
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None

        # 解析 frontmatter
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        meta_text = parts[1]
        content = parts[2].strip()

        meta: dict[str, str] = {}
        for line in meta_text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()

        if "name" not in meta:
            return None

        tools_str = meta.get("tools", "")
        tools = [t.strip() for t in tools_str.split(",") if t.strip()]

        return Skill(
            name=meta["name"],
            description=meta.get("description", ""),
            trigger=meta.get("trigger", ""),
            content=content,
            content_path=str(path),
            tools=tools,
            category=meta.get("category", ""),
            disable_model_invocation=meta.get(
                "disable_model_invocation", ""
            ).lower() == "true",
        )

    # ---------- 查询 ----------

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def model_invoked_skills(self) -> list[Skill]:
        """返回所有 model-invoked 技能（可被模型自动加载）。"""
        return [
            s for s in self._skills.values()
            if not s.disable_model_invocation
        ]

    def user_invoked_skills(self) -> list[Skill]:
        """返回所有 user-invoked 技能（仅用户主动触发）。"""
        return [
            s for s in self._skills.values()
            if s.disable_model_invocation
        ]

    def skills_by_category(self) -> dict[str, list[Skill]]:
        """按分类分组返回技能。"""
        result: dict[str, list[Skill]] = {}
        for skill in self._skills.values():
            cat = skill.category or "other"
            result.setdefault(cat, []).append(skill)
        return result

    # ---------- 元数据提示 ----------

    def metadata_prompt(self) -> str:
        """生成技能元数据提示，注入系统提示。

        只包含 model-invoked 技能（disable_model_invocation=False）。
        user-invoked 技能不在此列出，由用户主动输入触发。
        """
        model_invoked = self.model_invoked_skills()
        user_invoked = self.user_invoked_skills()

        if not model_invoked and not user_invoked:
            return ""

        lines = ["## Available Skills", ""]

        # ---------- Model-invoked 技能 ----------
        if model_invoked:
            lines.append(
                "你可以通过 load_skill 工具加载以下技能的完整内容。"
                "当任务匹配触发条件时，ALWAYS 先 load_skill 再执行。"
            )
            lines.append("")

            by_category = self.skills_by_category()
            for cat, skills in sorted(by_category.items()):
                # 只列出 model-invoked 的
                model_skills = [
                    s for s in skills if not s.disable_model_invocation
                ]
                if not model_skills:
                    continue

                lines.append(f"### {cat}")
                for skill in sorted(model_skills, key=lambda s: s.name):
                    lines.append(f"- **{skill.name}**: {skill.description}")
                    if skill.trigger:
                        lines.append(f"  触发条件: {skill.trigger}")
                lines.append("")

        # ---------- User-invoked 技能（只列名字）----------
        if user_invoked:
            lines.append("### 用户主动触发的技能")
            lines.append(
                "以下技能不会自动触发。用户在输入框输入 `/技能名` 时激活："
            )
            lines.append("")
            for skill in sorted(user_invoked, key=lambda s: s.name):
                lines.append(f"- `/{skill.name}`: {skill.description}")
            lines.append("")

        return "\n".join(lines)

    # ---------- 工具关联 ----------

    def filter_tools_for_skill(self, skill_name: str) -> list[str]:
        """返回技能关联的工具名。"""
        skill = self._skills.get(skill_name)
        return skill.tools if skill else []

    # ---------- 统计 ----------

    def stats(self) -> dict:
        return {
            "total": len(self._skills),
            "model_invoked": len(self.model_invoked_skills()),
            "user_invoked": len(self.user_invoked_skills()),
            "categories": list(self.skills_by_category().keys()),
        }