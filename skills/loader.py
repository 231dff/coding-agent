"""Skill 加载与解析。

frontmatter 字段：
- name / category / description / disable_model_invocation / hidden / tools

提供 create_load_skill_tool(registry) 把 load_skill(name) 包装成
LangChain tool。

编码兼容：优先 UTF-8，失败回退 GBK（Windows 默认），最后 replace。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.tools import tool

if TYPE_CHECKING:
    from skills.registry import SkillRegistry


DEFAULT_CATEGORY = "其他"

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$",
    re.DOTALL,
)


# ============================================================
# 数据模型
# ============================================================


@dataclass
class Skill:
    name: str
    description: str
    category: str = DEFAULT_CATEGORY
    disable_model_invocation: bool = False
    hidden: bool = False
    tools: list[str] = field(default_factory=list)
    path: Path | None = None
    body: str = ""
    raw_meta: dict[str, Any] = field(default_factory=dict)

    def load(self) -> str:
        if self.body:
            return self.body
        if self.path and self.path.is_file():
            text = _read_text_safe(self.path)
            if text is None:
                return ""
            _, body = _split_frontmatter(text)
            self.body = body
            return body
        return ""


# ============================================================
# 编码安全的读取
# ============================================================


def _read_text_safe(path: Path) -> str | None:
    """优先 UTF-8，回退 GBK，最后 replace。

    Windows 上 write_text 不指定 encoding 时默认是 cp936（GBK），
    单用 UTF-8 读会抛 UnicodeDecodeError。
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pass
    except Exception:
        return None

    try:
        return path.read_text(encoding="gbk")
    except Exception:
        pass

    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


# ============================================================
# frontmatter 解析
# ============================================================


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    meta_text = m.group(1)
    body = m.group(2)

    try:
        import yaml

        meta = yaml.safe_load(meta_text) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}

    return meta, body


def _parse_bool(raw, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off", ""):
        return False
    return default


def _normalize_name(stem: str) -> str:
    return stem.strip().replace(" ", "-")


def _clean_description(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)
    return re.sub(r"\s+", " ", str(raw)).strip()


def _extract_lead(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        return line[:200]
    return ""


def _infer_category(path: Path) -> str:
    try:
        parent = path.parent
        if parent.name in ("definitions", "skills"):
            return DEFAULT_CATEGORY
        if parent.parent and parent.parent.name in ("definitions", "skills"):
            return parent.name
        return parent.name
    except Exception:
        return DEFAULT_CATEGORY


# ============================================================
# 单文件加载
# ============================================================


def load_skill_file(path: Path) -> Skill | None:
    if not path.is_file():
        return None
    if path.suffix.lower() != ".md":
        return None

    text = _read_text_safe(path)
    if text is None:
        return None

    meta, body = _split_frontmatter(text)

    name = str(meta.get("name") or "").strip() or _normalize_name(path.stem)

    description = _clean_description(meta.get("description"))
    if not description:
        description = _extract_lead(body)

    category = str(meta.get("category") or "").strip() or _infer_category(path)
    if not category:
        category = DEFAULT_CATEGORY

    disable = _parse_bool(meta.get("disable_model_invocation"), default=False)
    hidden = _parse_bool(meta.get("hidden"), default=False)

    tools_raw = meta.get("tools") or []
    if isinstance(tools_raw, str):
        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
    elif isinstance(tools_raw, list):
        tools = [str(t).strip() for t in tools_raw if str(t).strip()]
    else:
        tools = []

    return Skill(
        name=name,
        description=description,
        category=category,
        disable_model_invocation=disable,
        hidden=hidden,
        tools=tools,
        path=path,
        body=body,
        raw_meta=meta,
    )


# ============================================================
# 目录扫描
# ============================================================


def load_skills_from_dir(
    root: Path,
    recursive: bool = True,
) -> list[Skill]:
    if not root.is_dir():
        return []

    pattern = "**/*.md" if recursive else "*.md"
    skills: list[Skill] = []
    seen_names: set[str] = set()

    for path in sorted(root.glob(pattern)):
        if any(p.startswith("_") or p.startswith(".") for p in path.parts):
            continue
        skill = load_skill_file(path)
        if skill is None:
            continue
        if skill.name in seen_names:
            continue
        seen_names.add(skill.name)
        skills.append(skill)

    return skills


# ============================================================
# load_skill 工具
# ============================================================


def create_load_skill_tool(registry: SkillRegistry):
    @tool
    def load_skill(skill_name: str) -> str:
        """加载指定技能的完整内容。

        当任务命中某个技能的触发条件时，先用这个工具加载它，再按
        其指导执行。技能列表和触发条件见系统提示的
        `## Available Skills` 段落。

        Args:
            skill_name: 技能名（kebab-case 或 snake_case），
                例如 "code-review"、"tdd"、"diagnosing-bugs"。
        """
        skill = registry.get(skill_name)
        if skill is None:
            all_names = [s.name for s in registry.all_skills()]
            suggestions = [
                n
                for n in all_names
                if skill_name.lower() in n.lower() or n.lower() in skill_name.lower()
            ][:5]
            msg = f"ERROR: 未知技能: {skill_name}"
            if suggestions:
                msg += f"。你是不是想找: {', '.join(suggestions)}？"
            return msg

        content = skill.load()
        if not content:
            return f"ERROR: 技能内容为空: {skill_name}"

        return f'<skill name="{skill.name}">\n{content}\n</skill>'

    return load_skill


# ============================================================
# 导出
# ============================================================

__all__ = [
    "Skill",
    "DEFAULT_CATEGORY",
    "load_skill_file",
    "load_skills_from_dir",
    "create_load_skill_tool",
]
