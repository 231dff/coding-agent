"""Agent CLI 入口。

用法：
    coding-agent init [--project PATH]
    coding-agent [--project PATH] [--model MODEL] [task]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path

from langchain_core.messages import AIMessageChunk, ToolMessage
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from agent.config import AgentConfig, resolve_project_path
from agent.core import build_agent
from agent.setup_wizard import maybe_run_first_time_setup, run_setup_wizard
from memory.card_extractor import extract_and_save

# ---------- 双层记忆 ----------
from memory.cards import user_card_repo
from memory.pending import (
    PendingTask,
    add_pending,
    load_pending,
    remove_pending,
)
from memory.session_summary import (
    session_summary_repo,
    summarize_session,
)
from memory.store import (
    current_user_id,
    store_backend_info,
)
from observability.logger import (
    bind_context,
    configure_logging,
    get_logger,
    log_file_path,
)
from observability.metrics_display import MetricsDisplay
from observability.trace import (
    get_trace_id,
    new_trace_id,
    reset_trace_id,
)
from observability.tracing import (
    configure as configure_tracing,
)
from observability.tracing import (
    is_enabled,
    status_text,
)

console = Console()
log = get_logger("main")


# ============================================================
# 环境变量小工具
# ============================================================


def _env_bool(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).lower() == "true"


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# ============================================================
# 单字母/短别名映射
# ============================================================

_ALIASES = {
    "exit": "/exit",
    "quit": "/exit",
    "q": "/exit",
    "h": "/help",
    "?": "/help",
    "help": "/help",
    "s": "/stats",
    "t": "/thinking",
    "c": "/config",
    "m": "/memory",
    "k": "/skills",
    "cards": "/cards",
    "r": "/recall",
    "e": "/eval",
    "u": "/users",
}


# ============================================================
# ASCII art 启动横幅
# ============================================================

_BANNER_ART = r"""
 ██████╗ ██████╗ ██████╗ ██╗███╗   ██╗ ██████╗
██╔════╝██╔═══██╗██╔══██╗██║████╗  ██║██╔════╝
██║     ██║   ██║██║  ██║██║██╔██╗ ██║██║  ███╗
██║     ██║   ██║██║  ██║██║██║╚██╗██║██║   ██║
╚██████╗╚██████╔╝██████╔╝██║██║ ╚████║╚██████╔╝
 ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝
"""

BANNER = _BANNER_ART


def _silence_noisy_loggers() -> None:
    import logging

    if os.getenv("AGENT_VERBOSE_LOGS", "false").lower() in ("1", "true", "yes"):
        return

    noisy_prefixes = (
        "httpx",
        "httpcore",
        "mcp",
        "langchain_openai",
        "openai",
        "urllib3",
        "filelock",
        "asyncio",
        "matplotlib",
        "autotest",
    )
    for name in list(logging.root.manager.loggerDict.keys()):
        if any(name.startswith(p) for p in noisy_prefixes):
            logging.getLogger(name).setLevel(logging.WARNING)
    for p in noisy_prefixes:
        logging.getLogger(p).setLevel(logging.WARNING)


def _default_thread_id(project_path: Path) -> str:
    """默认 thread_id —— 按天隔离，防止 checkpointer 无限累积。

    同一天内共享上下文（可以"接着刚才的做"），跨天自动重置。
    跨天不丢记忆：用户卡片 / 会话摘要存在 memory/ 里。
    """
    from datetime import datetime

    key = str(project_path.resolve()) + datetime.now().strftime("%Y%m%d")
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def _boot_agent_with_status(cfg):
    with console.status(
        "[cyan]正在装配 Agent…[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        rt = build_agent(cfg)
    return rt


def _print_ready_line(rt) -> None:
    mcp_prefixes = ("mcp_", "github_", "filesystem_", "fetch_", "git_", "postgres_")
    mcp_count = sum(1 for t in rt.tools if any(t.name.startswith(p) for p in mcp_prefixes))
    skill_count = len(rt.skill_registry.all_skills()) if rt.skill_registry else 0

    user = current_user_id()

    parts = [
        "[bold green]✓[/bold green] [white]已就绪[/white]",
        f"[dim]tools={len(rt.tools)}[/dim]",
    ]
    if mcp_count:
        parts.append(f"[dim]mcp={mcp_count}[/dim]")
    parts.append(f"[dim]skills={skill_count}[/dim]")
    parts.append(f"[dim]user={user}[/dim]")

    console.print("  " + "  ".join(parts))


# ============================================================
# Claude 风格：先规划再执行
# ============================================================

_COMPLEX_TASK_PATTERNS = [
    r"写.{0,8}(?:一个|个).{0,25}(?:系统|框架|平台|应用|工具|服务)",
    r"实现.{0,12}(?:系统|框架|平台|应用|工具)",
    r"设计.{0,12}(?:系统|框架|平台|应用)",
    r"创建.{0,12}(?:项目|系统|框架|应用)",
    r"搭建.{0,12}(?:系统|框架|平台)",
    r"从零.{0,10}(?:实现|搭建|构建)",
    r"帮我做.{0,20}",
    r"给我写.{0,20}(?:系统|框架|平台|应用|工具)",
]

_COMPLEX_TASK_MIN_LEN = 25


def _is_complex_task(text: str) -> bool:
    """判断是否是复杂任务——需要先给策略。"""
    if os.getenv("AGENT_PLAN_FIRST", "on").lower() == "off":
        return False

    for pattern in _COMPLEX_TASK_PATTERNS:
        if re.search(pattern, text):
            return True

    if len(text.strip()) >= _COMPLEX_TASK_MIN_LEN:
        return True

    return False


_PLANNER_SYSTEM = """你是一个实现规划师。用户提出了一个任务，你需要给出 2-4 个**明显不同**的实现策略，让用户选择。

每个策略必须包含：
- name: 简短的名字（4-8 个字）
- desc: 一句话说明怎么做（20-40 字）
- pros: 这个方案最大的优点（10-20 字）
- cons: 这个方案最大的缺点（10-20 字）

策略之间必须**真的不同**——不能只是命名不同、内容雷同。

只输出 JSON，不要任何其他内容（不要 markdown 代码块）：

{
  "plans": [
    {"name": "方案名1", "desc": "说明", "pros": "优点", "cons": "缺点"},
    {"name": "方案名2", "desc": "说明", "pros": "优点", "cons": "缺点"}
  ]
}
"""


def _extract_content_from_resp(resp) -> str:
    c = getattr(resp, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(c)


def _parse_plans(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data.get("plans", [])
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    return data.get("plans", [])
            except json.JSONDecodeError:
                pass
    return []


def _plan_and_choose(rt, task: str) -> str | None:
    """生成方案让用户选。返回选中方案的描述文本（供注入上下文）。

    用户取消（q / Ctrl+C）时返回 None。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agent.core import _build_compaction_llm

    console.print()
    with console.status(
        "[cyan]分析任务，生成实现策略…[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        try:
            llm = _build_compaction_llm(rt.config)
            resp = llm.invoke(
                [
                    SystemMessage(content=_PLANNER_SYSTEM),
                    HumanMessage(content=f"用户任务：{task}"),
                ]
            )
            raw = _extract_content_from_resp(resp)
        except Exception as e:
            console.print(f"[yellow]规划失败：{e}，直接执行[/yellow]")
            return None

    plans = _parse_plans(raw)

    if not plans:
        console.print("[dim]未能解析出方案，直接执行[/dim]")
        return None

    t = Table(show_header=False, box=None, padding=(0, 2), expand=False)
    t.add_column("#", style="bold cyan", width=3, no_wrap=True)
    t.add_column("方案", style="bold white", width=12, no_wrap=True)
    t.add_column("说明与权衡", style="white")

    for i, p in enumerate(plans, 1):
        name = p.get("name", f"方案 {i}")
        desc = p.get("desc", "")
        pros = p.get("pros", "")
        cons = p.get("cons", "")

        detail_lines = [desc] if desc else []
        if pros:
            detail_lines.append(f"[green]✓[/green] {pros}")
        if cons:
            detail_lines.append(f"[red]✗[/red] {cons}")

        t.add_row(str(i), name, "\n".join(detail_lines))

    console.print()
    console.print(
        Panel(
            t,
            title="[bold bright_cyan]请选择实现策略[/bold bright_cyan]",
            border_style="bright_cyan",
            expand=False,
        )
    )
    console.print(
        f"[dim]输入 [bold cyan]1[/bold cyan]-[bold cyan]{len(plans)}[/bold cyan] 选择，"
        f"[bold cyan]q[/bold cyan] 取消[/dim]"
    )

    while True:
        try:
            ans = input("\n你的选择 > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]已取消[/yellow]")
            return None

        if ans in ("q", "quit", "exit", "取消"):
            console.print("[dim]已取消[/dim]")
            return None

        if ans.isdigit():
            idx = int(ans)
            if 1 <= idx <= len(plans):
                picked = plans[idx - 1]
                name = picked.get("name", "")
                desc = picked.get("desc", "")
                console.print(f"\n[green]✓ 已选择 [{idx}] {name}[/green]")
                console.print()

                return (
                    f"【用户已选择方案 [{idx}] {name}】\n"
                    f"实现思路：{desc}\n"
                    f"请严格按此方案执行，不要再调用 propose_plan。"
                )

        console.print(f"[red]请输入 1-{len(plans)} 之间的数字，或 q 取消[/red]")


# ============================================================
# 轨迹文件轮换
# ============================================================


def _rotate_trajectory(rt, thread_id: str) -> None:
    tw = getattr(rt, "trajectory_writer", None)
    if tw is None:
        return
    from datetime import datetime as _dt

    new_sid = f"session-{thread_id}-{_dt.now():%Y%m%d-%H%M%S}"
    try:
        tw.rotate(new_sid)
        log.info("trajectory_rotated", new_path=str(tw.path))
    except Exception as e:
        log.warning("trajectory_rotate_failed", error=str(e))


# ============================================================
# 欢迎屏
# ============================================================


def _build_welcome_banner():
    from rich import box
    from rich.align import Align

    art = Text(_BANNER_ART.strip("\n"), style="bold bright_cyan", no_wrap=True)
    tagline = Text(
        "Read it.  Change it.  Test it.  Fix it.",
        style="italic dim white",
        justify="center",
    )
    content = Text.assemble(art, "\n\n", tagline)
    return Panel(
        Align.center(content, vertical="middle"),
        box=box.ROUNDED,
        border_style="bright_cyan",
        padding=(1, 4),
    )


def _build_welcome_info(project_path, rt, thread_id: str | None = None):
    from rich.table import Table as _Table

    cfg = rt.config

    info = _Table(
        show_header=False,
        show_edge=False,
        box=None,
        padding=(0, 2),
        expand=False,
    )
    info.add_column("icon", style="bright_cyan", width=3, justify="center")
    info.add_column("key", style="dim", width=6, justify="right")
    info.add_column("value", style="")

    info.add_row("📁", "项目", f"[white]{project_path}[/white]")
    info.add_row(
        "🧠",
        "模型",
        f"[white]{cfg.provider_id}[/white][dim] / [/dim][bright_white]{cfg.model}[/bright_white]",
    )

    if rt.skill_registry:
        stats = rt.skill_registry.stats()
        total = stats["model_invoked"] + stats["user_invoked"]
        info.add_row(
            "🔧",
            "技能",
            f"[white]{total}[/white] 个 "
            f"[dim]({stats['model_invoked']} 自动 · {stats['user_invoked']} 手动)[/dim]",
        )

    mem = store_backend_info()
    info.add_row(
        "💾",
        "记忆",
        f"[white]{mem.get('backend', '?')}[/white] [dim]({mem.get('type', '?')})[/dim]",
    )

    info.add_row("👤", "用户", f"[dim]{current_user_id()}[/dim]")

    if is_enabled():
        info.add_row("🔍", "追踪", f"[green]{status_text()}[/green]")
    else:
        info.add_row("🔍", "追踪", "[dim]未启用[/dim]")

    if thread_id:
        info.add_row("🆔", "会话", f"[dim]{thread_id}[/dim]")

    return info


def _build_welcome_hints():
    t = Text(justify="center")
    t.append("💡  ", style="")
    t.append("直接输入任务描述", style="white")
    t.append("，", style="dim")
    t.append("Enter", style="bold cyan")
    t.append(" 发送", style="dim")
    t.append("\n")
    t.append("📖  ", style="")
    t.append("输入 ", style="dim")
    t.append("/help", style="bold cyan")
    t.append(" 查看全部命令", style="dim")
    return t


def print_welcome(project_path: Path, rt, thread_id: str | None = None) -> None:
    from rich.align import Align

    console.print()
    console.print(_build_welcome_banner())
    console.print()
    console.print(Align.center(_build_welcome_info(project_path, rt, thread_id)))
    console.print()
    console.print(Align.center(_build_welcome_hints()))
    console.print()


# ============================================================
# 帮助
# ============================================================


def print_help(show_all: bool = False) -> None:
    t = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
        expand=False,
    )
    t.add_column("cmd", style="bold cyan", width=18, no_wrap=True)
    t.add_column("desc", style="white", width=22, no_wrap=True)
    t.add_column("cmd2", style="bold cyan", width=18, no_wrap=True)
    t.add_column("desc2", style="white", width=22, no_wrap=True)

    t.add_row("[bold yellow]核心[/bold yellow]", "", "", "")
    t.add_row("/exit  (q)", "退出", "/help  (h, ?)", "显示帮助")
    t.add_row("/clear", "清空会话状态", "", "")

    t.add_row("", "", "", "")

    t.add_row("[bold yellow]查看[/bold yellow]", "", "", "")
    t.add_row("/stats  (s)", "运行统计", "/thinking  (t)", "上次思考")
    t.add_row("/config  (c)", "当前配置", "/skills  (k)", "技能列表")
    t.add_row("/memory  (m)", "记忆状态", "/cards", "用户卡片")
    t.add_row("/users  (u)", "多用户审计", "/recall <q>  (r)", "检索历史")

    t.add_row("", "", "", "")

    if show_all:
        t.add_row("[bold yellow]高级[/bold yellow]", "", "", "")
        t.add_row("/eval  (e)", "回归测试", "/metrics", "（等同 /stats）")
        t.add_row("/trace", "（等同 /stats）", "", "")
        t.add_row("", "", "", "")

    t.add_row("[bold yellow]技能[/bold yellow]", "", "", "")
    t.add_row("/<name>", "加载 user-invoked 技能", "", "")

    if not show_all:
        t.add_row("", "", "", "")
        t.add_row(
            "[dim]输入 [/dim][bold]/help --all[/bold][dim] 查看全部命令[/dim]",
            "",
            "",
            "",
        )

    console.print(Panel(t, title="Help", border_style="dim", expand=False))


# ============================================================
# 查看类命令
# ============================================================


def list_skills(rt) -> None:
    registry = rt.skill_registry
    if not registry:
        console.print("[dim]未加载技能[/dim]")
        return
    by_cat = registry.skills_by_category()
    for cat, skills in sorted(by_cat.items()):
        console.print(f"\n[bold cyan]{cat}[/bold cyan]")
        for skill in sorted(skills, key=lambda s: s.name):
            tag = (
                "[yellow]user [/yellow]"
                if skill.disable_model_invocation
                else "[green]model[/green]"
            )
            prefix = "/" if skill.disable_model_invocation else " "
            console.print(f"  {tag} {prefix}{skill.name}: {skill.description[:80]}")
    console.print()


def show_config(rt) -> None:
    cfg = rt.config
    from agent.config import global_config_file, project_config_file

    lines = [f"  [bold]{k}:[/bold] {v}" for k, v in cfg.to_dict().items()]
    lines.append("")
    lines.append(f"  [dim]全局配置: {global_config_file()}[/dim]")
    lines.append(f"  [dim]项目配置: {project_config_file(cfg.project_path)}[/dim]")
    if is_enabled():
        lines.append(f"  [dim]LangSmith: {status_text()}[/dim]")
    console.print(Panel("\n".join(lines), title="当前配置"))


def show_metrics(rt) -> None:
    try:
        from api.metrics_timeseries import get_store

        store = get_store()
        stats = store.stats()
        console.print(
            Panel(
                f"  [bold]存储文件:[/bold] {stats['db_path']}\n"
                f"  [bold]总行数:[/bold] {stats['total_rows']}\n"
                f"  [bold]文件大小:[/bold] {stats['db_size_bytes'] / 1024:.1f} KB",
                title="指标存储",
            )
        )
    except Exception as e:
        console.print(f"[red]获取指标失败: {e}[/red]")


def show_trace(display: MetricsDisplay) -> None:
    display.dump_recent(30)


# ============================================================
# ★ 多用户隔离审计
# ============================================================


def _show_users_audit() -> None:
    """列出所有 user_id 及其数据量（用于隔离自查）。"""
    try:
        from memory.store import current_user_id as _cur_uid
        from memory.store import get_store

        store = get_store()
        cur = _cur_uid()

        try:
            namespaces = store.list_namespaces()
        except Exception as e:
            console.print(f"[red]无法列出 namespace: {e}[/red]")
            return

        user_stats: dict[str, dict[str, int]] = {}
        for ns in namespaces:
            if len(ns) < 3 or ns[0] != "users":
                continue
            uid = ns[1]
            kind = ns[2] if len(ns) > 2 else "?"
            user_stats.setdefault(uid, {"cards": 0, "summaries": 0, "other": 0})
            try:
                items = store.search(ns, limit=100000)
                n = len(items)
            except Exception:
                n = 0
            if kind == "cards":
                user_stats[uid]["cards"] += n
            elif kind == "summaries":
                user_stats[uid]["summaries"] += n
            else:
                user_stats[uid]["other"] += n

        if not user_stats:
            console.print("[dim]暂无任何用户数据[/dim]")
            return

        t = Table(show_header=True, box=None)
        t.add_column("user_id", style="cyan")
        t.add_column("cards", justify="right")
        t.add_column("summaries", justify="right")
        t.add_column("other", justify="right")
        t.add_column("", justify="left")

        for uid in sorted(user_stats.keys()):
            s = user_stats[uid]
            marker = "← 当前" if uid == cur else ""
            t.add_row(
                uid,
                str(s["cards"]),
                str(s["summaries"]),
                str(s["other"]),
                marker,
            )

        console.print(Panel(t, title="用户隔离审计", border_style="cyan"))
    except Exception as e:
        console.print(f"[red]/users 失败: {e}[/red]")


# ============================================================
# 思考过程查询
# ============================================================


def _thinking_path(rt, thread_id: str) -> Path:
    d = rt.config.trajectory_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{thread_id}_thinking.jsonl"


def _save_thinking_trace(rt, thread_id: str, turns: list[dict]) -> None:
    path = _thinking_path(rt, thread_id)
    with open(path, "a", encoding="utf-8") as f:
        for turn in turns:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def show_thinking(rt, thread_id: str) -> None:
    path = _thinking_path(rt, thread_id)
    if not path.exists():
        console.print("[dim]暂无思考记录[/dim]")
        return

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    if not lines:
        console.print("[dim]暂无思考记录[/dim]")
        return

    segments: list[list[dict]] = []
    current: list[dict] = []
    for line in lines:
        try:
            turn = json.loads(line)
        except Exception:
            continue
        if turn.get("round") == 1 and current:
            segments.append(current)
            current = []
        current.append(turn)
    if current:
        segments.append(current)

    if not segments:
        console.print("[dim]暂无思考记录[/dim]")
        return

    latest = segments[-1]

    parts: list[str] = []
    for turn in latest:
        r = turn.get("round", "?")
        content = turn.get("content", "")
        tools = turn.get("tool_calls", [])
        reasoning = turn.get("reasoning", "")

        parts.append(f"[bold cyan]## 第 {r} 轮[/bold cyan]")
        if tools:
            parts.append(f"[dim]工具: {', '.join(tools)}[/dim]")
        if reasoning:
            parts.append(f"[dim italic]{reasoning}[/dim italic]")
        if content:
            parts.append(content)
        parts.append("")

    console.print(
        Panel(
            "\n".join(parts),
            title=f"思考过程（{len(latest)} 轮）",
            border_style="dim",
        )
    )


# ============================================================
# 记忆相关命令
# ============================================================


def show_cards() -> None:
    try:
        repo = user_card_repo()
        cards = repo.load_active()
    except Exception as e:
        console.print(f"[red]读取卡片失败: {e}[/red]")
        return

    if not cards:
        console.print("[dim]暂无卡片。跑几次任务后会自动生成。[/dim]")
        return

    groups: dict[str, list] = {}
    for c in cards:
        groups.setdefault(c.category, []).append(c)

    lines = [f"[bold]共 {len(cards)} 条卡片[/bold]", ""]
    for cat, items in sorted(groups.items()):
        lines.append(f"[bold cyan]## {cat}[/bold cyan]")
        for c in items:
            conf = f" [dim]({c.confidence:.2f})[/dim]" if c.confidence < 0.8 else ""
            lines.append(f"  {c.fact}{conf}")
        lines.append("")
    console.print(Panel("\n".join(lines), title="用户卡片（第 1 层）"))


def show_recall(query: str) -> None:
    try:
        from memory.retriever import get_retriever

        items = get_retriever(user_id=current_user_id()).search(
            query=query,
            top_k=5,
        )
    except Exception as e:
        console.print(f"[red]检索失败: {e}[/red]")
        return

    if not items:
        console.print("[dim]未找到相关历史会话[/dim]")
        return

    lines = [f"[bold]查询:[/bold] {query}", ""]
    for i, item in enumerate(items, 1):
        source_tag = f" [{item.source}]" if item.source else ""
        lines.append(
            f"[bold cyan]{i}. [{item.task_type}]{source_tag} score={item.score}[/bold cyan]"
        )
        lines.append(f"   {item.summary}")
        lines.append("")
    console.print(Panel("\n".join(lines), title="历史会话检索（第 2 层）"))


def _retriever_display_info(user_id: str) -> str:
    kind = os.getenv("AGENT_RETRIEVER", "bm25").lower()
    if kind == "bm25":
        return "BM25（关键词）"

    try:
        from memory.retriever import _RETRIEVER_CACHE

        cache_key = f"{kind}:{user_id}"
        retriever = _RETRIEVER_CACHE.get(cache_key)
    except Exception:
        retriever = None

    if retriever is None:
        model = os.getenv("AGENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        if kind == "chroma":
            return (
                f"ChromaDB（未初始化，模型={model}）\n"
                f"      首次使用时会下载模型，运行一个任务后重试"
            )
        if kind == "hybrid":
            return (
                f"Hybrid（未初始化，模型={model}）\n      首次使用时会下载模型，运行一个任务后重试"
            )
        return f"{kind}（未初始化）"

    cls = type(retriever).__name__

    if cls == "HybridRetriever":
        try:
            if retriever.is_hybrid:
                n = retriever.chroma.count() if retriever.chroma else 0
                return f"Hybrid（向量 {n} 条 + BM25）"
        except Exception:
            pass
        err = getattr(retriever.chroma, "_init_error", "未知") if retriever.chroma else "未启用"
        return f"Hybrid（降级：{str(err)[:40]}）"

    if cls == "ChromaRetriever":
        try:
            return f"ChromaDB（{retriever.count()} 条向量）"
        except Exception:
            return "ChromaDB"

    return f"{kind}（未知类型 {cls}）"


def show_memory_status() -> None:
    info = store_backend_info()
    user_id = current_user_id()

    try:
        n_cards = len(user_card_repo(user_id=user_id).load_active())
    except Exception:
        n_cards = "?"

    try:
        n_summaries = len(session_summary_repo(user_id=user_id).load_all())
    except Exception:
        n_summaries = "?"

    retriever_info = _retriever_display_info(user_id)

    from memory.store import agent_home

    console.print(
        Panel(
            f"  [bold]后端:[/bold] {info.get('backend', '?')} "
            f"({info.get('type', '?')})\n"
            f"  [bold]用户:[/bold] {user_id}\n"
            f"  [bold]存储根:[/bold] {agent_home()}\n"
            f"\n"
            f"  [bold]第 1 层（卡片）:[/bold] {n_cards} 条\n"
            f"  [bold]第 2 层（会话摘要）:[/bold] {n_summaries} 条\n"
            f"  [bold]检索器:[/bold] {retriever_info}\n"
            f"\n"
            f"  [dim]切换后端:[/dim]\n"
            f"  [dim]  AGENT_STORE_BACKEND=sqlite|postgres|memory[/dim]\n"
            f"  [dim]  AGENT_RETRIEVER=bm25|chroma|hybrid[/dim]\n"
            f"  [dim]  AGENT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5[/dim]",
            title="长期记忆",
        )
    )


# ============================================================
# 会话结束钩子
# ============================================================


def _do_extraction(rt, thread_id: str) -> None:
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = rt.agent.get_state(config)
        if state is None or not state.values:
            remove_pending(rt.config.meta_dir, thread_id)
            return

        messages = state.values.get("messages", [])
        if not messages or len(messages) < 4:
            remove_pending(rt.config.meta_dir, thread_id)
            return

        from agent.core import _build_compaction_llm

        llm = _build_compaction_llm(rt.config)

        user_id = current_user_id()
        project_path = str(rt.config.project_path)

        if os.getenv("AGENT_USER_MEMORY", "true").lower() == "true":
            try:
                extract_and_save(llm, messages, session_id=thread_id)
            except Exception as e:
                log.warning("card_extraction_failed", error=str(e))

        if os.getenv("AGENT_RETRIEVAL", "true").lower() == "true":
            try:
                summary = summarize_session(
                    llm,
                    messages,
                    session_id=thread_id,
                    user_id=user_id,
                    project_path=project_path,
                )
                if summary and summary.summary:
                    session_summary_repo(user_id=user_id).add(summary)
                    try:
                        from memory.retriever import get_retriever

                        get_retriever(user_id=user_id).index(summary)
                    except Exception as idx_err:
                        log.warning("retriever_index_failed", error=str(idx_err))
            except Exception as e:
                log.warning("session_summary_failed", error=str(e))

        remove_pending(rt.config.meta_dir, thread_id)

    except Exception as e:
        log.warning("extraction_failed", error=str(e))


def extract_and_save_memory_async(rt, thread_id: str) -> None:
    meta_dir = rt.config.meta_dir
    try:
        add_pending(
            meta_dir,
            PendingTask(
                thread_id=thread_id,
                project_path=str(rt.config.project_path),
                user_id=current_user_id(),
            ),
        )
    except Exception as e:
        log.warning("add_pending_failed", error=str(e))

    def _run():
        try:
            _do_extraction(rt, thread_id)
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True, name="memory-extract")
    t.start()
    t.join(timeout=1.0)


def process_pending_on_startup(rt, current_thread_id: str) -> None:
    try:
        meta_dir = rt.config.meta_dir
        tasks = load_pending(meta_dir)
        if not tasks:
            return

        to_process = [t for t in tasks if t.thread_id != current_thread_id]
        if not to_process:
            return

        def _run():
            for task in to_process:
                try:
                    _do_extraction(rt, task.thread_id)
                except Exception as e:
                    log.warning(
                        "pending_extraction_failed",
                        thread_id=task.thread_id,
                        error=str(e),
                    )

        t = threading.Thread(target=_run, daemon=True, name="pending-extract")
        t.start()
    except Exception as e:
        log.warning("process_pending_failed", error=str(e))


# ============================================================
# 第 3 步：摘要聚合
# ============================================================


def process_summary_aggregation_on_startup(rt) -> None:
    """启动时检查是否要聚合旧摘要（后台静默跑）。

    触发条件：未聚合 raw 摘要数 >= AGENT_AGGREGATE_THRESHOLD（默认 20）。
    """
    if not _env_bool("AGENT_AUTO_AGGREGATE", "true"):
        return

    threshold = _env_int("AGENT_AGGREGATE_THRESHOLD", 20)

    def _run():
        try:
            from agent.core import _build_compaction_llm
            from memory.session_summary import session_summary_repo
            from memory.summary_aggregator import aggregate_summaries

            repo = session_summary_repo()
            raw_items = repo.find_unaggregated_raw()
            if len(raw_items) < threshold:
                return

            llm = _build_compaction_llm(rt.config)
            result = aggregate_summaries(llm, repo, threshold=threshold)
            if result.get("created", 0) > 0:
                log.info("summary_aggregated", **result)
        except Exception as e:
            log.warning("summary_aggregation_failed", error=str(e))

    t = threading.Thread(target=_run, daemon=True, name="summary-aggregate")
    t.start()


# ============================================================
# 经验归档
# ============================================================


def _archive_experience(rt, thread_id: str, task: str) -> None:
    try:
        import json as _json
        import time as _time

        from agent.evolution.store import ExperienceRecord, get_store
        from verification import TrajectoryVerifier, load_events
        from verification.schema import Verdict

        tw = getattr(rt, "trajectory_writer", None)
        if tw is None:
            return

        traj_path = Path(tw.path)
        if not traj_path.exists():
            return

        try:
            tw.flush_now(timeout=2.0)
        except Exception:
            pass

        events = load_events(traj_path)
        if not events:
            return

        verifier = TrajectoryVerifier()
        diag = verifier.verify(task_id=traj_path.stem, events=events)

        failed_dims = [d.name for d in diag.dimensions if d.verdict == Verdict.FAIL]
        uncertain_dims = [d.name for d in diag.dimensions if d.verdict == Verdict.UNCERTAIN]

        reviewer_verdict = ""
        reviewer_confidence = 0.0
        reviewer_issues = []
        for e in events:
            if e.type == "tool_result" and e.name == "review_changes":
                text = e.content or ""
                try:
                    data = _json.loads(text)
                    reviewer_verdict = data.get("verdict", "")
                    reviewer_confidence = float(data.get("confidence", 0.0))
                    reviewer_issues = data.get("issues", [])
                except Exception:
                    pass
                break

        files_changed = []
        for e in events:
            if e.type == "tool_call" and e.name in (
                "write_file",
                "edit_file",
                "apply_patch",
                "sandbox_write",
            ):
                args = e.args or {}
                p = args.get("path") or args.get("file_path") or ""
                if p and p not in files_changed:
                    files_changed.append(p)

        tool_calls = sum(1 for e in events if e.type == "tool_call")

        record = ExperienceRecord(
            ts=_time.time(),
            session_id=thread_id,
            task=task[:500],
            verdict=diag.overall_verdict.value,
            veto_triggered=diag.veto_triggered,
            success=diag.success,
            failed_dimensions=failed_dims,
            uncertain_dimensions=uncertain_dims,
            reviewer_verdict=reviewer_verdict,
            reviewer_confidence=reviewer_confidence,
            reviewer_issues=reviewer_issues,
            files_changed=files_changed,
            tool_calls_count=tool_calls,
        )
        get_store().record(record)
        log.info("experience_archived", session_id=thread_id, verdict=record.verdict)
    except Exception as e:
        log.warning("experience_archive_failed", error=str(e))


# ============================================================
# 自动进化
# ============================================================

_AUTO_EVOLVE_COUNTER = "auto-evolve-counter.txt"


def _auto_evolve_silent(rt) -> None:
    try:
        from agent.core import _build_compaction_llm
        from agent.evolution.aggregator import ExperienceAggregator
        from agent.evolution.runner import _render_proposal
        from agent.evolution.store import get_store

        store = get_store()
        window = _env_int("AGENT_AUTO_EVOLVE_WINDOW", 30)
        records = store.load_recent(n=window)
        if not records:
            return

        llm = _build_compaction_llm(rt.config)
        aggregator = ExperienceAggregator(llm)
        result = aggregator.aggregate(records, existing_rules="")

        if "error" in result:
            log.warning("auto_evolve_aggregator_error", error=result["error"])
            return

        stats = ExperienceAggregator._statistical_summary(records)
        proposal_md = _render_proposal(result, records, stats)
        path = store.save_proposal(proposal_md)
        log.info("auto_evolve_proposal_saved", path=str(path))

        if _env_bool("AGENT_AUTO_EVOLVE_APPLY", "false"):
            _apply_high_global_rules(rt, result)
    except Exception as e:
        log.warning("auto_evolve_failed", error=str(e))


def _apply_high_global_rules(rt, result: dict) -> None:
    try:
        rules = [
            r
            for r in result.get("candidate_rules", [])
            if r.get("priority") == "high" and r.get("scope") == "global"
        ]
        if not rules:
            return

        prompt_path = rt.config.agent_home / "prompts" / "system_v1.md"
        if not prompt_path.exists():
            return

        original = prompt_path.read_text(encoding="utf-8")
        appended = original + "\n\n## 从经验中提炼的规则\n"
        for r in rules:
            appended += f"\n- {r.get('rule', '')}"

        backup = prompt_path.with_suffix(".md.bak")
        backup.write_text(original, encoding="utf-8")
        prompt_path.write_text(appended, encoding="utf-8")
        log.info("auto_evolve_applied", count=len(rules), backup=str(backup))
    except Exception as e:
        log.warning("auto_evolve_apply_failed", error=str(e))


def _maybe_auto_evolve(rt) -> None:
    if not _env_bool("AGENT_AUTO_EVOLVE", "true"):
        return

    threshold = _env_int("AGENT_AUTO_EVOLVE_THRESHOLD", 10)
    counter_path = rt.config.meta_dir / _AUTO_EVOLVE_COUNTER

    try:
        count = int(counter_path.read_text().strip()) if counter_path.exists() else 0
    except Exception:
        count = 0

    count += 1

    if count < threshold:
        try:
            counter_path.parent.mkdir(parents=True, exist_ok=True)
            counter_path.write_text(str(count), encoding="utf-8")
        except Exception:
            pass
        return

    try:
        counter_path.write_text("0", encoding="utf-8")
    except Exception:
        pass

    def _run():
        try:
            _auto_evolve_silent(rt)
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True, name="auto-evolve")
    t.start()


# ============================================================
# 参数解析
# ============================================================


def parse_agent_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description="Coding Agent — 对任意项目进行代码理解、修改与测试",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--thread-id",
        default=None,
        help="会话 ID（默认按项目路径自动生成，可跨重启恢复）",
    )
    parser.add_argument("task", nargs="?", default=None)
    return parser.parse_args()


# ============================================================
# 流式渲染辅助
# ============================================================


def _extract_reasoning(chunk) -> str:
    ak = getattr(chunk, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        v = ak.get("reasoning_content")
        if v:
            return v

    v = getattr(chunk, "reasoning_content", None)
    if v:
        return v

    rm = getattr(chunk, "response_metadata", None) or {}
    if isinstance(rm, dict):
        v = rm.get("reasoning_content")
        if v:
            return v

    return ""


def _extract_content(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _extract_tool_name(tc) -> str:
    if isinstance(tc, dict):
        return tc.get("name") or ""
    return getattr(tc, "name", "") or ""


def _dedup_repeats(text: str) -> str:
    if len(text) < 400:
        return text

    n = len(text)
    for seg_len in (500, 300, 200, 150):
        if seg_len * 2 > n:
            continue
        seg = text[n // 2 : n // 2 + seg_len]
        if not seg.strip():
            continue
        idx = text.find(seg, n // 2 + seg_len)
        if idx > 0:
            return text[:idx].rstrip()
    return text


# ============================================================
# 流式任务执行
# ============================================================


def stream_task_with_reasoning(rt, task: str, thread_id: str) -> str:
    turns: list[dict] = []
    cur_content: list[str] = []
    cur_reasoning: list[str] = []
    cur_tool_calls: list[str] = []

    reasoning_display: list[str] = []
    tool_events: list[str] = []
    tool_seen: set[str] = set()
    _last_update = [0.0]
    _t0 = [time.time()]

    TOOL_DISPLAY_MAX = 6

    def seal_round() -> None:
        nonlocal cur_content, cur_reasoning, cur_tool_calls
        if cur_content or cur_reasoning or cur_tool_calls:
            turns.append(
                {
                    "round": len(turns) + 1,
                    "content": "".join(cur_content),
                    "reasoning": "".join(cur_reasoning),
                    "tool_calls": list(cur_tool_calls),
                }
            )
        cur_content = []
        cur_reasoning = []
        cur_tool_calls = []

    def build_display() -> Text:
        t = Text()
        if tool_events:
            for line in tool_events[-TOOL_DISPLAY_MAX:]:
                t.append(line + "\n", style="cyan")
            t.append("\n")
        elapsed = time.time() - _t0[0]
        t.append(f"💭 思考中… ({elapsed:.1f}s)", style="dim italic")
        return t

    use_live = console.is_terminal
    live = (
        Live(
            build_display(),
            console=console,
            refresh_per_second=4,
            transient=True,
            vertical_overflow="visible",
        )
        if use_live
        else nullcontext()
    )

    with live:
        for chunk in rt.agent.stream(
            {"messages": [{"role": "user", "content": task}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": rt.config.max_iterations * 2,
            },
            stream_mode="messages",
        ):
            msg = chunk[0] if isinstance(chunk, tuple) else chunk
            if msg is None:
                continue

            if isinstance(msg, AIMessageChunk):
                tcc = getattr(msg, "tool_call_chunks", None) or []
                for tc in tcc:
                    name = _extract_tool_name(tc)
                    if name and name not in cur_tool_calls:
                        cur_tool_calls.append(name)

                tc_full = getattr(msg, "tool_calls", None) or []
                for tc in tc_full:
                    name = _extract_tool_name(tc)
                    if name and name not in cur_tool_calls:
                        cur_tool_calls.append(name)

                c = _extract_content(msg)
                if c:
                    cur_content.append(c)

                r = _extract_reasoning(msg)
                if r:
                    cur_reasoning.append(r)
                    reasoning_display.append(r)

            elif isinstance(msg, ToolMessage):
                name = getattr(msg, "name", "tool") or "tool"
                if name not in tool_seen:
                    tool_seen.add(name)
                    tool_events.append(f"  ⚙ {name} ✓")
                    if not use_live:
                        console.print(f"  ⚙ {name} ✓")

                seal_round()
                reasoning_display.clear()

            now = time.time()
            if use_live and now - _last_update[0] > 0.25:
                live.update(build_display())
                _last_update[0] = now

        seal_round()
        if use_live:
            live.update(build_display())

    try:
        _save_thinking_trace(rt, thread_id, turns)
    except Exception as e:
        log.warning("save_thinking_trace_failed", error=str(e))

    for turn in reversed(turns):
        if turn["content"]:
            return _dedup_repeats(turn["content"])
    return ""


# ============================================================
# 单次任务 / 交互模式
# ============================================================


def _print_final(content: str, rt, thread_id: str, turns_count: int) -> None:
    console.print()
    if content:
        console.print(Panel(Markdown(content), title="回复", border_style="cyan"))
    else:
        console.print(
            Panel("[dim](模型无文本输出，可能是工具调用已完成)[/dim]", border_style="cyan")
        )

    if turns_count > 1:
        console.print(
            f"[dim]💭 思考过程: {turns_count} 轮 · 输入 [bold]/thinking[/bold] 查看[/dim]"
        )


def run_single_task(rt, task: str, thread_id: str, display: MetricsDisplay) -> None:
    console.print(f"[bold green]任务:[/bold green] {task}\n")

    _rotate_trajectory(rt, thread_id)

    # 复杂任务先规划再执行
    if _is_complex_task(task):
        choice_context = _plan_and_choose(rt, task)
        if choice_context is None:
            return  # 用户取消
        task = f"{task}\n\n{choice_context}"

    try:
        content = stream_task_with_reasoning(rt, task, thread_id)
        display.flush()

        turns_count = 0
        try:
            path = _thinking_path(rt, thread_id)
            if path.exists():
                lines = path.read_text(encoding="utf-8").strip().split("\n")
                for line in reversed(lines):
                    try:
                        turn = json.loads(line)
                    except Exception:
                        continue
                    if turn.get("round") == 1 and turns_count > 0:
                        break
                    turns_count += 1
        except Exception:
            pass

        _print_final(content, rt, thread_id, turns_count)

        _archive_experience(rt, thread_id, task)
        _maybe_auto_evolve(rt)

    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")
    except Exception as e:
        log.error(
            "single_task_failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        console.print(f"\n[red]错误: {type(e).__name__}: {e}[/red]")


def handle_user_invoked_skill(rt, user_input: str) -> str | None:
    if not user_input.startswith("/"):
        return None
    parts = user_input[1:].split(maxsplit=1)
    skill_name = parts[0]
    extra_args = parts[1] if len(parts) > 1 else ""

    registry = rt.skill_registry
    if not registry:
        return None

    skill = registry.get(skill_name)
    if skill is None:
        return None
    if not skill.disable_model_invocation:
        console.print(f"[yellow]{skill_name} 是 model-invoked 技能，模型会自动调用[/yellow]")
        return None

    console.print(f"[dim]加载技能: {skill_name}[/dim]")
    skill_content = skill.load()
    task = f"[技能激活: {skill_name}]\n\n{skill_content}"
    if extra_args:
        task += f"\n\n用户输入: {extra_args}"
    task += "\n\n请按上述技能指导执行。"
    return task


def run_interactive(rt, thread_id: str, display: MetricsDisplay) -> None:
    while True:
        try:
            user_input = Prompt.ask("[bold cyan]你[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        lower_input = user_input.lower()

        if lower_input in _ALIASES:
            user_input = _ALIASES[lower_input]
            lower_input = user_input.lower()

        if lower_input in ("/exit", "/quit", "exit", "quit"):
            console.print("[dim]再见[/dim]")
            break

        if lower_input.startswith("/help"):
            show_all = "--all" in user_input.lower()
            print_help(show_all=show_all)
            continue

        if lower_input in ("/clear", "clear"):
            rt.status_bar.reset()
            console.print("[dim]会话状态已清空[/dim]")
            continue
        if lower_input in ("/skills", "skills"):
            list_skills(rt)
            continue
        if lower_input in ("/config", "config"):
            show_config(rt)
            continue
        if lower_input in ("/metrics", "metrics"):
            try:
                from agent.stats import collect, render_stats

                snap = collect(rt.config.meta_dir)
                render_stats(snap, console)
            except Exception as e:
                console.print(f"[red]/metrics 失败: {e}[/red]")
            continue
        if lower_input == "/trace":
            show_trace(display)
            continue
        if lower_input == "/thinking":
            show_thinking(rt, thread_id)
            continue
        if lower_input == "/cards":
            show_cards()
            continue
        if lower_input == "/memory":
            show_memory_status()
            continue
        if lower_input == "/users":
            _show_users_audit()
            continue

        if lower_input == "/stats":
            try:
                from agent.stats import collect, render_stats

                snap = collect(rt.config.meta_dir)
                render_stats(snap, console)
            except Exception as e:
                console.print(f"[red]/stats 失败: {e}[/red]")
            continue

        if lower_input.startswith("/eval"):
            parts = user_input[len("/eval") :].strip().split()
            subcmd = parts[0] if parts else "help"
            args = parts[1:]

            try:
                import time as _time

                from agent.eval import (
                    EvalDataset,
                    EvalRunner,
                    compare_with_baseline,
                    mine_cases,
                    render_report,
                )
                from agent.eval.reporter import save_report
                from agent.eval.schema import EvalReport

                eval_root = rt.config.meta_dir / "eval"
                dataset = EvalDataset(eval_root)

                if subcmd == "mine":
                    n = int(args[0]) if args and args[0].isdigit() else 20
                    cases = mine_cases(
                        rt.config.meta_dir / "evolution" / "experiences.jsonl",
                        dataset,
                        n=n,
                    )
                    console.print(f"[green]已挖掘 {len(cases)} 条案例[/green]")
                    console.print(f"[dim]保存至: {dataset.cases_path}[/dim]")

                elif subcmd == "list":
                    cases = dataset.load()
                    if not cases:
                        console.print("[dim]案例库为空。先跑 /eval mine[/dim]")
                    else:
                        t = Table(show_header=True, box=None)
                        t.add_column("case_id", style="dim")
                        t.add_column("category")
                        t.add_column("expected")
                        t.add_column("task")
                        for c in cases[:30]:
                            t.add_row(c.case_id, c.category, c.expected_verdict, c.task[:40])
                        console.print(t)

                elif subcmd == "run":
                    cases = dataset.load()
                    if not cases:
                        console.print("[red]案例库为空。先跑 /eval mine[/red]")
                    else:
                        console.print(f"[dim]跑 {len(cases)} 条案例...[/dim]")
                        runner = EvalRunner(rt)
                        report = EvalReport(
                            total=len(cases),
                            started_at=_time.time(),
                        )
                        for i, c in enumerate(cases, 1):
                            console.print(
                                f"[dim]({i}/{len(cases)}) {c.case_id}...[/dim]",
                                end=" ",
                            )
                            r = runner.run_one(c)
                            report.results.append(r)
                            if r.error:
                                report.errors += 1
                                console.print("[yellow]![/yellow]")
                            elif r.success:
                                report.passed += 1
                                console.print("[green]✓[/green]")
                            else:
                                report.failed += 1
                                console.print("[red]✗[/red]")

                        report.finished_at = _time.time()

                        baseline = eval_root / "baseline.json"
                        compare_with_baseline(report, baseline)

                        render_report(report, cases, console, verbose=False)

                        if not baseline.exists():
                            save_report(report, baseline)
                            console.print(f"[green]已保存为 baseline: {baseline}[/green]")
                        else:
                            save_report(
                                report,
                                eval_root / f"run-{int(_time.time())}.json",
                            )

                else:
                    console.print(
                        "[bold]用法[/bold]\n"
                        "  /eval mine [N]  从历史经验挖 N 条案例（默认 20）\n"
                        "  /eval list      列出案例库\n"
                        "  /eval run       跑所有案例并对比 baseline"
                    )

            except Exception as e:
                console.print(f"[red]/eval 失败: {type(e).__name__}: {e}[/red]")
            continue

        if lower_input.startswith("/recall"):
            q = user_input[len("/recall") :].strip()
            if q:
                show_recall(q)
            else:
                console.print("[red]用法: /recall <查询词>[/red]")
            continue

        task_text = user_input
        if user_input.startswith("/"):
            handled = handle_user_invoked_skill(rt, user_input)
            if handled is None:
                console.print(
                    f"[red]未知命令或技能: {user_input}[/red]\n[dim]输入 /help 查看命令[/dim]"
                )
                continue
            task_text = handled

        # 复杂任务先规划再执行
        if _is_complex_task(task_text):
            choice_context = _plan_and_choose(rt, task_text)
            if choice_context is None:
                continue  # 用户取消，回到 prompt
            task_text = f"{task_text}\n\n{choice_context}"

        bind_context(
            session_id=rt.config.project_path.name,
            thread_id=thread_id,
            trace_id=get_trace_id(),
        )

        _rotate_trajectory(rt, thread_id)

        try:
            console.print()
            content = stream_task_with_reasoning(rt, task_text, thread_id)
            display.flush()

            turns_count = 0
            try:
                path = _thinking_path(rt, thread_id)
                if path.exists():
                    lines = path.read_text(encoding="utf-8").strip().split("\n")
                    for line in reversed(lines):
                        try:
                            turn = json.loads(line)
                        except Exception:
                            continue
                        if turn.get("round") == 1 and turns_count > 0:
                            break
                        turns_count += 1
            except Exception:
                pass

            _print_final(content, rt, thread_id, turns_count)

            _archive_experience(rt, thread_id, task_text)
            _maybe_auto_evolve(rt)

        except KeyboardInterrupt:
            console.print("\n[yellow]已中断[/yellow]")
        except Exception as e:
            log.error(
                "task_failed",
                error_type=type(e).__name__,
                error=str(e),
            )
            console.print(f"\n[red]错误: {type(e).__name__}: {e}[/red]\n")


# ============================================================
# init 子命令
# ============================================================


def cmd_init(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="coding-agent init")
    parser.add_argument("--project", "-p", default=None)
    parsed = parser.parse_args(args)

    try:
        project_path = resolve_project_path(parsed.project)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    ok = run_setup_wizard(project_path)
    return 0 if ok else 1


# ============================================================
# 主入口
# ============================================================


def main() -> int:
    json_logs = os.getenv("LOG_JSON", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "INFO")
    configure_logging(level=log_level, json_output=json_logs)

    _silence_noisy_loggers()

    tid = new_trace_id()

    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
        configure_tracing(
            project=os.getenv("LANGCHAIN_PROJECT", "coding-agent"),
        )

    args = sys.argv[1:]

    if args and args[0] == "init":
        return cmd_init(args[1:])

    parsed = parse_agent_args()

    try:
        project_path = resolve_project_path(parsed.project)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    maybe_run_first_time_setup(project_path)

    try:
        cfg = AgentConfig.load(
            project_path=project_path,
            **({"model": parsed.model} if parsed.model else {}),
        )
        cfg.validate()
    except ValueError as e:
        console.print(f"[red]配置错误: {e}[/red]")
        console.print("[dim]运行 `coding-agent init` 配置模型[/dim]")
        return 1

    cfg.ensure_gitignore()

    thread_id = parsed.thread_id or _default_thread_id(project_path)

    bind_context(trace_id=tid, thread_id=thread_id)

    try:
        rt = _boot_agent_with_status(cfg)
    except Exception as e:
        log.error(
            "agent_start_failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        console.print(f"[red]Agent 启动失败: {type(e).__name__}: {e}[/red]")
        console.print(f"[dim]详细日志: {log_file_path()}[/dim]")
        return 1

    try:
        process_pending_on_startup(rt, thread_id)
    except Exception:
        pass

    # 第 3 步：启动时检查摘要聚合
    try:
        process_summary_aggregation_on_startup(rt)
    except Exception:
        pass

    display = MetricsDisplay(rt.metrics_queue, console)
    display.start()

    try:
        if parsed.task:
            _print_ready_line(rt)
            console.print()
            run_single_task(rt, parsed.task, thread_id, display)
        else:
            print_welcome(project_path, rt, thread_id=thread_id)
            run_interactive(rt, thread_id, display)
    finally:
        try:
            extract_and_save_memory_async(rt, thread_id)
        except Exception:
            pass

        display.stop()
        rt.close()
        reset_trace_id()

    return 0


if __name__ == "__main__":
    sys.exit(main())
