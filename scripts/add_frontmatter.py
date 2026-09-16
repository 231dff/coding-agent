"""批量给 skills/definitions/*.md 加 frontmatter。

用法：
    cd <项目根目录>
    python scripts/add_frontmatter.py --dry-run   # 预览
    python scripts/add_frontmatter.py             # 实际写入
    python scripts/add_frontmatter.py --force     # 覆盖已有 frontmatter
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# name -> (category, description, disable_model_invocation, hidden)
MAPPING: dict[str, tuple[str, str, bool, bool]] = {
    # ======================================================
    # 实现与测试
    # ======================================================
    "tdd": (
        "实现与测试",
        '测试驱动开发。触发：用户说"TDD"、"红绿重构"、"先写测试"、'
        '"test-first"、要求集成测试。不触发：只是跑一下现有测试、只是 debug 测试失败。',
        False,
        False,
    ),
    "tdd_tests": (
        "实现与测试",
        "TDD 子文档：测试编写细则。内部引用，不单独触发。",
        False,
        True,
    ),
    "tdd_mocking": (
        "实现与测试",
        "TDD 子文档：mock 策略。内部引用，不单独触发。",
        False,
        True,
    ),
    "implement": (
        "实现与测试",
        '按 spec/ticket 实现功能。触发：用户输入 /implement，或明确说"按 spec 实现"。'
        "不触发：没敲 / 且只是普通实现需求（用 tdd / codebase-design）。",
        True,
        False,
    ),
    "prototype": (
        "实现与测试",
        '构建一次性原型验证设计。触发：用户说"先做个原型"、"试一下这个方案"、'
        '"看看这个 UI 长什么样"。不触发：直接上生产、完整实现。',
        False,
        False,
    ),
    "prototype_LOGIC": (
        "实现与测试",
        "prototype 子文档：逻辑原型。内部引用，不单独触发。",
        False,
        True,
    ),
    "prototype_UI": (
        "实现与测试",
        "prototype 子文档：UI 原型。内部引用，不单独触发。",
        False,
        True,
    ),
    "python_testing": (
        "实现与测试",
        'Python 测试配置与调试。触发：用户说"配 pytest"、"补测试"、'
        '"测试覆盖率"、pytest 失败排查。不触发：非 Python 项目、只是跑测试。',
        False,
        False,
    ),
    "scaffold-exercises": (
        "实现与测试",
        "生成练习脚手架。触发：用户要创建教学/练习目录结构。不触发：创建生产项目。",
        False,
        False,
    ),
    # ======================================================
    # 设计与研究
    # ======================================================
    "codebase-design": (
        "设计与研究",
        '模块界面设计、寻找 deepen 机会、决定 seam 位置。触发：用户说"设计这个模块"、'
        '"这个接口怎么分"、"哪里可以解耦"、"让代码更好测"。'
        "不触发：只是实现、只是 review。",
        False,
        False,
    ),
    "codebase-design_DEEPENING": (
        "设计与研究",
        "codebase-design 子文档：深化阶段细则。内部引用，不单独触发。",
        False,
        True,
    ),
    "codebase-design_DESIGN-IT-TWICE": (
        "设计与研究",
        "codebase-design 子文档：两次设计法。内部引用，不单独触发。",
        False,
        True,
    ),
    "domain-modeling": (
        "设计与研究",
        '领域建模、术语梳理、ADR、CONTEXT.md。触发：用户说"梳理领域概念"、'
        '"写 ADR"、"更新 CONTEXT.md"、"统一术语"。不触发：只是改字段、只是 CRUD。',
        False,
        False,
    ),
    "domain-modeling_ADR-FORMAT": (
        "设计与研究",
        "domain-modeling 子文档：ADR 格式。内部引用，不单独触发。",
        False,
        True,
    ),
    "domain-modeling_CONTEXT-FORMAT": (
        "设计与研究",
        "domain-modeling 子文档：CONTEXT.md 格式。内部引用，不单独触发。",
        False,
        True,
    ),
    "improve-codebase-architecture": (
        "设计与研究",
        "扫描代码库找架构改进机会，产出 HTML 报告。触发：用户输入 "
        "/improve-codebase-architecture。不触发：没敲 / 且只是局部重构。",
        True,
        False,
    ),
    "improve-codebase-architecture_HTML-REPORT": (
        "设计与研究",
        "improve-codebase-architecture 子文档：HTML 报告格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "research": (
        "设计与研究",
        '调研技术方案 / 未知领域，产出 Markdown 文件。触发：用户说"调研一下 X"、'
        '"查一下最佳实践"、"做个技术选型"。不触发：只是查 API 文档、只是问一句。',
        False,
        False,
    ),
    # ======================================================
    # 评审与诊断
    # ======================================================
    "code-review": (
        "评审与诊断",
        '代码评审。触发：用户说"review"、"评审"、"PR 看看"、"diff 看一下"、'
        '"从 X 开始的改动"。不触发：只是读代码、只是解释代码、只是跑测试。',
        False,
        False,
    ),
    "diagnosing-bugs": (
        "评审与诊断",
        '诊断难解的 bug 或性能回归。触发：用户说"诊断"、"debug"、'
        '"这个报错了"、"怎么这么慢"、"broken/failing"。不触发：只是写新功能、只是重构。',
        False,
        False,
    ),
    "resolving-merge-conflicts": (
        "评审与诊断",
        "解决进行中的 git merge/rebase 冲突。触发：git merge/rebase 有冲突、"
        '用户说"解决冲突"、"merge 挂了"。不触发：普通提交、普通拉取。',
        False,
        False,
    ),
    "grilling": (
        "评审与诊断",
        '深度拷问一个计划/决策/想法。触发：用户说"拷问我"、"challenge 我"、'
        '"压力测试这个方案"、"grill"。不触发：只是讨论方案、只是 review 代码。',
        False,
        False,
    ),
    # ======================================================
    # 工程配置
    # ======================================================
    "docker": (
        "工程配置",
        "Docker 镜像与容器编排。触发：用户改 Dockerfile/docker-compose、"
        '排查容器问题、说"容器化"。不触发：只是本地跑命令。',
        False,
        False,
    ),
    "database_migration": (
        "工程配置",
        "数据库 schema 迁移。触发：用户改 schema、加字段、写 Alembic 迁移、"
        '说"迁移数据"。不触发：只是查询、只是 CRUD。',
        False,
        False,
    ),
    "typescript_config": (
        "工程配置",
        "TS 项目配置与类型检查。触发：用户改 tsconfig、有类型错误、配 TS 构建。"
        "不触发：写业务 TS 代码。",
        False,
        False,
    ),
    "setup-pre-commit": (
        "工程配置",
        '配 Husky + lint-staged + 类型检查 + 测试。触发：用户说"加 pre-commit"、'
        '"配 Husky"、"提交前检查"。不触发：只是写 CI、只是写测试。',
        False,
        False,
    ),
    "git-guardrails-claude-code": (
        "工程配置",
        '配置 Claude Code hooks 拦截危险 git 命令。触发：用户说"拦截 git push"、'
        '"防止 reset --hard"、"配 git 安全钩子"。不触发：日常 git 操作。',
        False,
        False,
    ),
    "migrate-to-shoehorn": (
        "工程配置",
        "把测试里的 as 断言迁移到 shoehorn。触发：用户提到 shoehorn、"
        "要替换测试里的 as。不触发：其他迁移、其他重构。",
        False,
        False,
    ),
    "wizard": (
        "工程配置",
        "生成交互式 bash 向导，引导用户完成只有人能做的步骤。触发："
        "需要用户配置凭据、走第三方 dashboard、一次性迁移。"
        "不触发：Agent 自己能做的步骤。",
        False,
        False,
    ),
    # ======================================================
    # 文档与交接
    # ======================================================
    "writing-for-agents": (
        "文档与交接",
        '为 Agent 写文档（skill / AGENTS.md / CLAUDE.md）。触发：用户说"写个 skill"、'
        '"更新 AGENTS.md"、"改 CLAUDE.md"。不触发：写人类文档、写 README。',
        False,
        False,
    ),
    "writing-for-agents_SKILL-MECHANICS": (
        "文档与交接",
        "writing-for-agents 子文档：skill 机制。内部引用，不单独触发。",
        False,
        True,
    ),
    "handoff": (
        "文档与交接",
        '把当前对话压缩成交接文档。触发：用户输入 /handoff，或说"交接"、'
        '"总结一下给下一个 agent"。不触发：没敲 / 且任务还在进行。',
        True,
        False,
    ),
    "to-spec": (
        "文档与交接",
        "把当前对话转成 spec 并发到 issue tracker。触发：用户输入 /to-spec。不触发：没敲 /。",
        True,
        False,
    ),
    "to-tickets": (
        "文档与交接",
        "把 plan/spec 拆成 tickets。触发：用户输入 /to-tickets。不触发：没敲 /。",
        True,
        False,
    ),
    "to-questionnaire": (
        "文档与交接",
        "把决策转成问卷。触发：用户输入 /to-questionnaire。不触发：没敲 /。",
        True,
        False,
    ),
    # ======================================================
    # 用户主动触发
    # ======================================================
    "ask-matt": (
        "用户主动触发",
        "帮你判断该用哪个 skill 或流程。触发：用户输入 /ask-matt。不触发：没敲 /。",
        True,
        False,
    ),
    "ask-matt_PHASE-BOUNDARIES": (
        "用户主动触发",
        "ask-matt 子文档：阶段边界。内部引用，不单独触发。",
        True,
        True,
    ),
    "grill-me": (
        "用户主动触发",
        "拷问你的计划/设计。触发：用户输入 /grill-me。不触发：没敲 /。",
        True,
        False,
    ),
    "grill-with-docs": (
        "用户主动触发",
        "拷问 + 同时产出 ADR 和术语表。触发：用户输入 /grill-with-docs。不触发：没敲 /。",
        True,
        False,
    ),
    "setup-matt-pocock-skills": (
        "用户主动触发",
        "首次配置仓库（issue tracker、triage 标签、文档布局）。"
        "触发：用户输入 /setup-matt-pocock-skills。不触发：没敲 /。",
        True,
        False,
    ),
    "setup-matt-pocock-skills_domain": (
        "用户主动触发",
        "setup-matt-pocock-skills 子文档：domain 配置。内部引用，不单独触发。",
        True,
        True,
    ),
    "setup-matt-pocock-skills_issue-tracker-github": (
        "用户主动触发",
        "setup-matt-pocock-skills 子文档：GitHub tracker 配置。内部引用，不单独触发。",
        True,
        True,
    ),
    "setup-matt-pocock-skills_issue-tracker-gitlab": (
        "用户主动触发",
        "setup-matt-pocock-skills 子文档：GitLab tracker 配置。内部引用，不单独触发。",
        True,
        True,
    ),
    "setup-matt-pocock-skills_issue-tracker-local": (
        "用户主动触发",
        "setup-matt-pocock-skills 子文档：本地 tracker 配置。内部引用，不单独触发。",
        True,
        True,
    ),
    "setup-matt-pocock-skills_triage-labels": (
        "用户主动触发",
        "setup-matt-pocock-skills 子文档：triage 标签。内部引用，不单独触发。",
        True,
        True,
    ),
    "teach": (
        "用户主动触发",
        "教你一个新技能/概念。触发：用户输入 /teach。不触发：没敲 /。",
        True,
        False,
    ),
    "teach_GLOSSARY-FORMAT": (
        "用户主动触发",
        "teach 子文档：GLOSSARY 格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "teach_LEARNING-RECORD-FORMAT": (
        "用户主动触发",
        "teach 子文档：学习记录格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "teach_MISSION-FORMAT": (
        "用户主动触发",
        "teach 子文档：MISSION 格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "teach_RESOURCES-FORMAT": (
        "用户主动触发",
        "teach 子文档：RESOURCES 格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "triage": (
        "用户主动触发",
        "走 triage 状态机处理 issue 和外部 PR。触发：用户输入 /triage。不触发：没敲 /。",
        True,
        False,
    ),
    "triage_AGENT-BRIEF": (
        "用户主动触发",
        "triage 子文档：agent brief 格式。内部引用，不单独触发。",
        True,
        True,
    ),
    "triage_OUT-OF-SCOPE": (
        "用户主动触发",
        "triage 子文档：out-of-scope 处理。内部引用，不单独触发。",
        True,
        True,
    ),
    "wait-what": (
        "用户主动触发",
        "让模型重讲上一段。触发：用户输入 /wait-what。不触发：没敲 /。",
        True,
        False,
    ),
    "wayfinder": (
        "用户主动触发",
        "把超大块工作规划成决策 tickets 地图。触发：用户输入 /wayfinder。不触发：没敲 /。",
        True,
        False,
    ),
}


# ============================================================
# 写入逻辑
# ============================================================


def build_frontmatter(
    name: str,
    category: str,
    description: str,
    disable_model_invocation: bool,
    hidden: bool,
) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"category: {category}",
        f"description: {description}",
    ]
    if disable_model_invocation:
        lines.append("disable_model_invocation: true")
    if hidden:
        lines.append("hidden: true")
    lines.append("---")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def has_complete_frontmatter(text: str, name: str) -> bool:
    """判断文件是否已经有我们生成的完整 frontmatter。"""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return False
    end = stripped.find("---", 3)
    if end < 0:
        return False
    fm = stripped[: end + 3]
    return f"name: {name}" in fm and "category:" in fm


def process_file(path: Path, dry_run: bool = False, force: bool = False) -> str:
    name = path.stem

    if name not in MAPPING:
        return f"skip (no mapping): {path.name}"

    category, description, disable, hidden = MAPPING[name]

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error (read): {path.name}: {e}"

    if not force and has_complete_frontmatter(text, name):
        return f"skip (already has frontmatter): {path.name}"

    # 去掉旧的 frontmatter（如果有）
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("---", 3)
        if end > 0:
            text = stripped[end + 3 :].lstrip("\n")

    new_content = build_frontmatter(name, category, description, disable, hidden) + text

    if dry_run:
        tag = "hidden" if hidden else ("user" if disable else "model")
        return f"[dry-run] would update: {path.name}  ({category} / {tag})"

    try:
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"error (write): {path.name}: {e}"

    tag = "hidden" if hidden else ("user" if disable else "model")
    return f"updated: {path.name}  ({category} / {tag})"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="覆盖已有 frontmatter")
    parser.add_argument("--root", default="skills/definitions")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: 目录不存在: {root}", file=sys.stderr)
        print(f"      当前工作目录: {Path.cwd()}", file=sys.stderr)
        return 1

    files = sorted(root.glob("*.md"))
    if not files:
        print(f"ERROR: {root} 下没有 .md 文件", file=sys.stderr)
        return 1

    print(f"扫描目录: {root.resolve()}")
    print(f"共 {len(files)} 个 .md 文件")
    print()

    updated = skipped = errors = 0

    for f in files:
        result = process_file(f, dry_run=args.dry_run, force=args.force)
        print(result)
        if result.startswith("updated") or result.startswith("[dry-run]"):
            updated += 1
        elif result.startswith("skip"):
            skipped += 1
        elif result.startswith("error"):
            errors += 1

    print()
    print(f"结果: updated={updated}, skipped={skipped}, errors={errors}")

    unmapped = [f.stem for f in files if f.stem not in MAPPING]
    if unmapped:
        print()
        print("以下文件没有映射（需要手动加到 MAPPING）：")
        for name in sorted(unmapped):
            print(f"  - {name}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
