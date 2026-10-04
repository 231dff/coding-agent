"""P4: Rich 展示。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .schema import StatsSnapshot


def render_stats(snap: StatsSnapshot, console: Console | None = None) -> None:
    console = console or Console()

    if snap.total_tasks == 0:
        console.print("[dim]最近没有任务记录。跑几次任务再看。[/dim]")
        return

    # ---------- 1. 顶部概览 ----------
    console.print(_overview_panel(snap))

    # ---------- 2. 时间序列 ----------
    if snap.daily:
        console.print(_daily_panel(snap))

    # ---------- 3. 失败维度 ----------
    if snap.failed_dimensions:
        console.print(_failed_dims_panel(snap))

    # ---------- 4. 审查结果 ----------
    if snap.reviewer_distribution:
        console.print(_reviewer_panel(snap))

    # ---------- 5. 工具使用 ----------
    if snap.tool_usage:
        console.print(_tools_panel(snap))

    # ---------- 6. 成本 ----------
    if snap.total_cost_usd > 0:
        console.print(_cost_panel(snap))


# ---------- 内部 ----------

def _overview_panel(snap: StatsSnapshot) -> Panel:
    total = snap.total_tasks
    success_rate = snap.success_count / total * 100 if total else 0.0

    parts = [
        f"[bold]任务总数[/bold]  {total}",
        f"[green]成功[/green]  {snap.success_count}",
        f"[red]失败[/red]  {snap.fail_count}",
        f"[yellow]不确定[/yellow]  {snap.uncertain_count}",
    ]
    if snap.veto_count:
        parts.append(f"[bold red]一票否决[/bold red]  {snap.veto_count}")

    parts.append(f"[bold]成功率[/bold]  {success_rate:.1f}%")
    parts.append(f"[bold]平均工具调用[/bold]  {snap.avg_tool_calls:.1f}")

    return Panel("   ·   ".join(parts), title="总览", border_style="cyan")


def _daily_panel(snap: StatsSnapshot) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("日期", style="dim")
    table.add_column("任务数", justify="right")
    table.add_column("成功", justify="right", style="green")
    table.add_column("趋势", style="cyan")

    max_total = max((t for _, t, _ in snap.daily), default=1) or 1

    for d, total, success in snap.daily:
        bar_len = int(total / max_total * 20)
        bar = "█" * bar_len if bar_len > 0 else "·"
        success_marker = ""
        if total > 0:
            pct = success / total
            if pct >= 0.8:
                success_marker = "[green]✓[/green]"
            elif pct >= 0.5:
                success_marker = "[yellow]~[/yellow]"
            else:
                success_marker = "[red]✗[/red]"
        table.add_row(d[-5:], str(total), str(success), f"{bar} {success_marker}")

    return Panel(table, title="最近 7 天", border_style="dim")


def _failed_dims_panel(snap: StatsSnapshot) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("维度", style="bold")
    table.add_column("失败次数", justify="right", style="red")

    sorted_dims = sorted(
        snap.failed_dimensions.items(), key=lambda kv: kv[1], reverse=True
    )
    for name, count in sorted_dims[:8]:
        table.add_row(name, str(count))

    return Panel(table, title="高频失败维度", border_style="red")


def _reviewer_panel(snap: StatsSnapshot) -> Panel:
    lines = []
    total = sum(snap.reviewer_distribution.values())
    for verdict, count in sorted(
        snap.reviewer_distribution.items(), key=lambda kv: kv[1], reverse=True
    ):
        pct = count / total * 100 if total else 0
        color = {
            "approve": "green",
            "reject": "red",
            "needs_human": "yellow",
        }.get(verdict, "white")
        lines.append(f"[{color}]{verdict}[/{color}]  {count} ({pct:.0f}%)")

    return Panel("\n".join(lines), title="Reviewer 分布", border_style="yellow")


def _tools_panel(snap: StatsSnapshot) -> Panel:
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("工具", style="bold")
    table.add_column("调用次数", justify="right")

    sorted_tools = sorted(snap.tool_usage.items(), key=lambda kv: kv[1], reverse=True)
    for name, count in sorted_tools[:10]:
        table.add_row(name, str(count))

    return Panel(table, title="高频工具", border_style="cyan")


def _cost_panel(snap: StatsSnapshot) -> Panel:
    lines = [f"[bold]总成本[/bold]  [yellow]${snap.total_cost_usd:.4f}[/yellow]", ""]
    if snap.cost_by_model:
        lines.append("[dim]按模型[/dim]")
        for model, cost in sorted(
            snap.cost_by_model.items(), key=lambda kv: kv[1], reverse=True
        )[:5]:
            lines.append(f"  {model}  ${cost:.4f}")
    return Panel("\n".join(lines), title="成本", border_style="yellow")