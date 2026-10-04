"""P2-3: /evolve 主流程。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .aggregator import ExperienceAggregator
from .store import ExperienceRecord, get_store

console = Console()


def run_evolve(rt, n: int = 20, apply: bool = False) -> None:
    store = get_store()
    records = store.load_recent(n=n)

    if not records:
        console.print("[dim]还没有经验记录。跑几个任务再试。[/dim]")
        return

    console.print(f"[dim]分析最近 {len(records)} 条经验...[/dim]")

    stats = ExperienceAggregator._statistical_summary(records)
    console.print(_format_stats_panel(stats))

    from agent.core import _build_compaction_llm
    aggregator_llm = _build_compaction_llm(rt.config)

    aggregator = ExperienceAggregator(aggregator_llm)
    existing_rules = _load_current_prompt(rt)

    result = aggregator.aggregate(records, existing_rules)

    if "error" in result:
        console.print(f"[red]聚合失败: {result['error']}[/red]")
        return

    proposal_md = _render_proposal(result, records, stats)
    path = store.save_proposal(proposal_md)
    console.print(f"\n[green]提案已保存:[/green] {path}")

    console.print()
    console.print(_format_summary_panel(result))

    if apply:
        _apply_proposal(rt, result, path)
    else:
        console.print(
            "\n[dim]提示：候选规则保存在提案文件里，"
            "人工审核后再决定是否加入系统提示。[/dim]"
        )


def _load_current_prompt(rt) -> str:
    try:
        from agent.core import load_system_prompt
        return load_system_prompt(rt.config.agent_home)
    except Exception:
        return ""


def _format_stats_panel(stats: dict) -> Panel:
    lines = [
        f"**总记录**: {stats.get('total', 0)}",
        f"**判定分布**: {stats.get('verdict_distribution', {})}",
        f"**一票否决**: {stats.get('veto_count', 0)} 次",
        f"**Reviewer 分布**: {stats.get('reviewer_distribution', {})}",
    ]
    if stats.get("top_failed_dimensions"):
        lines.append(f"**高频失败维度**: {stats['top_failed_dimensions']}")
    return Panel("\n".join(lines), title="经验统计", border_style="cyan")


def _format_summary_panel(result: dict) -> Panel:
    lines = []
    failure = result.get("failure_patterns", [])
    if failure:
        lines.append(f"### 失败模式 ({len(failure)})")
        for p in failure[:5]:
            lines.append(f"- **{p.get('pattern', '?')}**")
            lines.append(f"  - 支持: {', '.join(p.get('supporting_sessions', [])[:3])}")
            if p.get("suggested_fix"):
                lines.append(f"  - 修复: {p['suggested_fix']}")
        lines.append("")
    candidate = result.get("candidate_rules", [])
    if candidate:
        lines.append(f"### 候选规则 ({len(candidate)})")
        for r in candidate[:5]:
            lines.append(f"- `[{r.get('priority', '?')}/{r.get('scope', '?')}]` {r.get('rule', '?')}")
    if not lines:
        lines.append("[dim]没有发现显著模式[/dim]")
    return Panel("\n".join(lines), title="分析摘要", border_style="green")


def _render_proposal(
    result: dict,
    records: list[ExperienceRecord],
    stats: dict,
) -> str:
    now = datetime.now()
    lines = [
        "# 持续进化提案",
        "",
        f"**生成时间**: {now:%Y-%m-%d %H:%M:%S}",
        f"**分析记录数**: {len(records)}",
        "",
        "## 统计摘要",
        "",
        f"- 判定分布: `{stats.get('verdict_distribution', {})}`",
        f"- 一票否决: {stats.get('veto_count', 0)} 次",
        f"- Reviewer 分布: `{stats.get('reviewer_distribution', {})}`",
        f"- 高频失败维度: `{stats.get('top_failed_dimensions', [])}`",
        "",
        "## 失败模式",
        "",
    ]
    for p in result.get("failure_patterns", []):
        lines.append(f"### {p.get('pattern', '?')}")
        lines.append(f"- 支持: {', '.join(p.get('supporting_sessions', []))}")
        lines.append(f"- 维度: `{p.get('dimension', '?')}`")
        lines.append(f"- 修复方向: {p.get('suggested_fix', '?')}")
        lines.append("")

    lines.extend(["## 候选规则", ""])
    for r in result.get("candidate_rules", []):
        lines.append(f"### `[{r.get('priority', '?')}/{r.get('scope', '?')}]`")
        lines.append("")
        lines.append("```")
        lines.append(r.get("rule", "?"))
        lines.append("```")
        lines.append("")
        lines.append(f"证据: {', '.join(r.get('evidence', []))}")
        lines.append("")

    lines.extend([
        "## 人工审核清单",
        "",
        "- [ ] 支持证据是否足够（≥2 条 session）",
        "- [ ] 与现有规则是否冲突",
        "- [ ] 是否引入过度约束",
        "- [ ] 应用后是否需要在保留集上回归测试",
        "",
        "## 应用方式",
        "",
        "1. 把 high 优先级、global 作用域的规则加入 `prompts/system_v1.md`",
        "2. 把 scope=coding 的规则加入项目级 `AGENTS.md`",
        "3. 把需要工具支持的规则做成 Skill",
        "4. 应用后跑一遍回归测试",
        "",
    ])
    return "\n".join(lines)


def _apply_proposal(rt, result: dict, proposal_path: Path) -> None:
    high_global = [
        r for r in result.get("candidate_rules", [])
        if r.get("priority") == "high" and r.get("scope") == "global"
    ]
    if not high_global:
        console.print("[dim]没有 high/global 规则需要自动应用[/dim]")
        return

    prompt_path = rt.config.agent_home / "prompts" / "system_v1.md"
    if not prompt_path.exists():
        console.print(f"[red]系统提示文件不存在: {prompt_path}[/red]")
        return

    original = prompt_path.read_text(encoding="utf-8")
    appended = original + "\n\n## 从经验中提炼的规则\n"
    for r in high_global:
        appended += f"\n- {r.get('rule', '')}"

    backup = prompt_path.with_suffix(".md.bak")
    backup.write_text(original, encoding="utf-8")
    prompt_path.write_text(appended, encoding="utf-8")

    console.print(f"[yellow]已应用 {len(high_global)} 条规则[/yellow]")
    console.print(f"[dim]备份: {backup}[/dim]")