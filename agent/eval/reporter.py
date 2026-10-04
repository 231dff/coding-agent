"""P4-2: 报告生成 + baseline 对比。"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .schema import EvalCase, EvalReport, EvalResult


def render_report(
    report: EvalReport,
    cases: list[EvalCase],
    console: Console | None = None,
    verbose: bool = False,
) -> None:
    console = console or Console()
    case_map = {c.case_id: c for c in cases}

    # 总览
    console.print(_overview_panel(report))

    # 失败的案例
    failed = [r for r in report.results if not r.success and not r.error]
    if failed:
        console.print(_failures_panel(failed, case_map))

    # 报错的案例
    errored = [r for r in report.results if r.error]
    if errored:
        console.print(_errors_panel(errored, case_map))

    # 回归
    if report.regressions:
        console.print(_regressions_panel(report.regressions, case_map))

    # 逐条明细（verbose）
    if verbose:
        console.print(_details_panel(report.results, case_map))


def compare_with_baseline(
    report: EvalReport,
    baseline_path: Path | str,
) -> None:
    """与 baseline 报告对比，填充 regressions / improvements。"""
    baseline_path = Path(baseline_path)
    if not baseline_path.exists():
        return

    try:
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:
        return

    base_results = {r["case_id"]: r for r in base.get("results", [])}
    for r in report.results:
        prev = base_results.get(r.case_id)
        if prev is None:
            continue
        prev_pass = bool(prev.get("success"))
        if prev_pass and not r.success:
            report.regressions.append(r.case_id)
        elif not prev_pass and r.success:
            report.improvements.append(r.case_id)
        else:
            report.unchanged += 1


def save_report(report: EvalReport, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "errors": report.errors,
        "pass_rate": report.pass_rate,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "regressions": report.regressions,
        "improvements": report.improvements,
        "unchanged": report.unchanged,
        "results": [r.__dict__ for r in report.results],
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------- 内部 ----------

def _overview_panel(report: EvalReport) -> Panel:
    elapsed = report.finished_at - report.started_at
    parts = [
        f"[bold]总数[/bold]  {report.total}",
        f"[green]通过[/green]  {report.passed}",
        f"[red]失败[/red]  {report.failed}",
        f"[yellow]报错[/yellow]  {report.errors}",
        f"[bold]通过率[/bold]  {report.pass_rate * 100:.1f}%",
        f"[dim]耗时 {elapsed:.1f}s[/dim]",
    ]
    if report.regressions:
        parts.append(f"[bold red]回归[/bold red]  {len(report.regressions)}")
    if report.improvements:
        parts.append(f"[bold green]改进[/bold green]  {len(report.improvements)}")
    return Panel("   ·   ".join(parts), title="Eval 总览", border_style="cyan")


def _failures_panel(
    failed: list[EvalResult],
    case_map: dict[str, EvalCase],
) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("case_id", style="dim", width=24)
    table.add_column("任务", style="bold")
    table.add_column("差异", style="red")

    for r in failed[:20]:
        c = case_map.get(r.case_id)
        task = (c.task[:40] + "...") if c and len(c.task) > 40 else (c.task if c else "?")
        table.add_row(r.case_id, task, r.diff_reason or "?")

    return Panel(table, title=f"失败案例 ({len(failed)})", border_style="red")


def _errors_panel(
    errored: list[EvalResult],
    case_map: dict[str, EvalCase],
) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("case_id", style="dim", width=24)
    table.add_column("错误", style="yellow")

    for r in errored[:20]:
        table.add_row(r.case_id, (r.error or "?")[:80])

    return Panel(table, title=f"报错案例 ({len(errored)})", border_style="yellow")


def _regressions_panel(
    regressions: list[str],
    case_map: dict[str, EvalCase],
) -> Panel:
    lines = []
    for cid in regressions[:15]:
        c = case_map.get(cid)
        task = (c.task[:60] + "...") if c and len(c.task) > 60 else (c.task if c else "?")
        lines.append(f"[red]✗[/red] {cid}  {task}")
    return Panel("\n".join(lines), title="⚠ 回归", border_style="red")


def _details_panel(
    results: list[EvalResult],
    case_map: dict[str, EvalCase],
) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("case_id", style="dim", width=24)
    table.add_column("状态", width=6)
    table.add_column("判定", width=12)
    table.add_column("工具", justify="right", width=5)
    table.add_column("耗时", justify="right", width=8)

    for r in results:
        status = "[green]✓[/green]" if r.success else (
            "[yellow]![/yellow]" if r.error else "[red]✗[/red]"
        )
        table.add_row(
            r.case_id,
            status,
            r.actual_verdict,
            str(r.tool_calls),
            f"{r.elapsed_s:.1f}s",
        )

    return Panel(table, title="明细", border_style="dim")
