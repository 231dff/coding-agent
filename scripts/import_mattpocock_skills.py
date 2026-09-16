"""将 mattpocock/skills 仓库的技能转换为本项目的格式。

用法：
    uv run python scripts/import_mattpocock_skills.py \
        --source D:/Github-agent/mattpocock-skills/skills \
        --target skills/definitions
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


# 技能名 → 触发条件映射（人工维护，覆盖常用技能）
TRIGGER_MAP: dict[str, str] = {
    # engineering
    "tdd": "当需要测试驱动开发、修复 bug、写集成测试时",
    "diagnosing-bugs": "当需要诊断难解的 bug 或性能回归时",
    "to-spec": "当需要把对话内容整理成规格文档时",
    "to-tickets": "当需要把计划或规格拆分为可执行的任务时",
    "implement": "当需要按规格或 Ticket 实现功能时",
    "triage": "当需要对 issue 进行分诊、打标签时",
    "wayfinder": "当需要规划超出单个会话能力的大任务时",
    "prototype": "当需要构建原型来验证设计问题时",
    "research": "当需要研究技术方案或调研未知领域时",
    "improve-codebase-architecture": "当需要扫描代码库、发现架构改进机会时",
    "ask-matt": "当不确定该用哪个技能时",
    "grill-with-docs": "当需要在开发前对齐需求、同时构建领域模型时",
    "setup-matt-pocock-skills": "当需要初始化项目的技能配置时",
    # productivity
    "grill-me": "当需要被拷问以锐化计划或设计时",
    "grilling": "当需要深度拷问一个计划、决策或想法时",
    "handoff": "当需要把当前对话压缩成交接文档时",
    "teach": "当需要学习新技能或概念时",
    "wait-what": "当某条消息没看懂、需要重新解释时",
    "writing-for-agents": "当需要为 Agent 写文档、技能或 AGENTS.md 时",
    "to-questionnaire": "当需要把决策转化为问卷时",
}


def parse_skill_md(path: Path) -> dict | None:
    """解析 mattpocock 格式的 SKILL.md。"""
    text = path.read_text(encoding="utf-8")

    # 提取 frontmatter
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return None

    fm_text, body = m.group(1), m.group(2)

    # 解析 YAML frontmatter（简单解析，不引入 pyyaml）
    meta: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")

    if "name" not in meta:
        return None

    return {
        "name": meta["name"],
        "description": meta.get("description", ""),
        "disable_model_invocation": meta.get("disable-model-invocation", "").lower() == "true",
        "body": body.strip(),
    }


def convert_to_project_format(skill: dict, category: str) -> str:
    """转换为本项目的技能格式。"""
    name = skill["name"]
    description = skill["description"]
    body = skill["body"]

    trigger = TRIGGER_MAP.get(name, f"当任务涉及 {name} 相关场景时")

    # 如果原始描述已经包含 "Use when"，提取触发条件
    if not TRIGGER_MAP.get(name) and "Use when" in description:
        trigger = description.split("Use when", 1)[1].strip()
        description = description.split("Use when", 1)[0].strip()

    # 转义 YAML 中的特殊字符
    description = description.replace(":", "：")
    trigger = trigger.replace(":", "：")

    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"trigger: {trigger}\n"
        f"category: {category}\n"
    )

    # 如果有 disable-model-invocation，加上标记
    if skill["disable_model_invocation"]:
        frontmatter += "disable_model_invocation: true\n"

    frontmatter += "---\n\n"

    return frontmatter + body + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="mattpocock/skills/skills 目录")
    parser.add_argument("--target", default="skills/definitions", help="目标目录")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)

    if not source.is_dir():
        print(f"错误：源目录不存在: {source}")
        return 1

    converted = 0
    skipped = 0

    # 遍历三个分类目录
    for category_dir in sorted(source.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name

        # 跳过 deprecated 和 in-progress
        if category in ("deprecated", "in-progress"):
            print(f"跳过分类: {category}")
            continue

        # 遍历分类下的技能目录
        for skill_dir in sorted(category_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            parsed = parse_skill_md(skill_file)
            if parsed is None:
                print(f"  跳过（解析失败）: {skill_file}")
                skipped += 1
                continue

            output = convert_to_project_format(parsed, category)
            output_file = target / f"{parsed['name']}.md"
            output_file.write_text(output, encoding="utf-8")

            print(f"  ✓ {category}/{parsed['name']} → {output_file.name}")
            converted += 1

            # 复制技能目录下的其他 .md 文件（如 tests.md、mocking.md）
            for extra in skill_dir.glob("*.md"):
                if extra.name == "SKILL.md":
                    continue
                extra_target = target / f"{parsed['name']}_{extra.stem}.md"
                extra_content = extra.read_text(encoding="utf-8")
                extra_target.write_text(extra_content, encoding="utf-8")
                print(f"    + 附加: {extra_target.name}")

    print(f"\n转换完成: {converted} 个技能，跳过 {skipped} 个")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())