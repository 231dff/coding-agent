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
import sys
import threading
import time
from pathlib import Path

from langchain_core.messages import AIMessageChunk, ToolMessage
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
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
# ASCII art 启动横幅（figlet ANSI Shadow 字体）
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


# ============================================================
# 静音第三方库日志
# ============================================================


def _silence_noisy_loggers() -> None:
    """静音第三方库的 INFO 级日志（httpx / mcp / openai 等）。

    这些库会输出大量 HTTP 请求细节，对最终用户无价值。

    用户可通过环境变量打开：
        AGENT_VERBOSE_LOGS=1   ← 调试时用
    """
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
    )

    # 动态遍历所有已注册 logger
    for name in list(logging.root.manager.loggerDict.keys()):
        if any(name.startswith(p) for p in noisy_prefixes):
            logging.getLogger(name).setLevel(logging.WARNING)

    # 兜底：直接按名设置（防止后续动态创建）
    for p in noisy_prefixes:
        logging.getLogger(p).setLevel(logging.WARNING)


# ============================================================
# 默认 thread_id
# ============================================================


def _default_thread_id(project_path: Path) -> str:
    key = str(project_path.resolve())
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


# ============================================================
# Agent 装配（带 spinner）
# ============================================================


def _boot_agent_with_status(cfg):
    """带 spinner 的 Agent 装配。

    - 整个装配过程（8~15 秒）只显示一个动态 spinner
    - 详细步骤由 build_agent 内部 log.info 记录，屏幕不显示
    - 装配完成后由调用方打印一行"已就绪"摘要
    - 异常 / Ctrl+C 由 rich.status 自动处理

    Returns:
        AgentRuntime
    """
    with console.status(
        "[cyan]正在装配 Agent…[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ):
        rt = build_agent(cfg)
    return rt


def _print_ready_line(rt) -> None:
    """打印一行"已就绪"摘要。"""
    mcp_prefixes = ("mcp_", "github_", "filesystem_", "fetch_", "git_", "postgres_")
    mcp_count = sum(
        1 for t in rt.tools if any(t.name.startswith(p) for p in mcp_prefixes)
    )
    skill_count = (
        len(rt.skill_registry.all_skills()) if rt.skill_registry else 0
    )

    parts = [
        f"[bold green]✓[/bold green] [white]已就绪[/white]",
        f"[dim]tools={len(rt.tools)}[/dim]",
    ]
    if mcp_count:
        parts.append(f"[dim]mcp={mcp_count}[/dim]")
    parts.append(f"[dim]skills={skill_count}[/dim]")

    console.print("  " + "  ".join(parts))


# ============================================================
# 欢迎屏（精致版）
# ============================================================


def _build_welcome_banner():
    """构建启动横幅：ASCII art + 标语，圆角框居中。"""
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
    """构建运行时信息表。"""
    from rich.table import Table

    cfg = rt.config

    info = Table(
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
        f"[white]{cfg.provider_id}[/white]"
        f"[dim] / [/dim]"
        f"[bright_white]{cfg.model}[/bright_white]",
    )

    if rt.skill_registry:
        stats = rt.skill_registry.stats()
        total = stats["model_invoked"] + stats["user_invoked"]
        info.add_row(
            "🔧",
            "技能",
            f"[white]{total}[/white] 个 "
            f"[dim]({stats['model_invoked']} 自动 · "
            f"{stats['user_invoked']} 手动)[/dim]",
        )

    mem = store_backend_info()
    info.add_row(
        "💾",
        "记忆",
        f"[white]{mem.get('backend', '?')}[/white] "
        f"[dim]({mem.get('type', '?')})[/dim]",
    )

    if is_enabled():
        info.add_row("🔍", "追踪", f"[green]{status_text()}[/green]")
    else:
        info.add_row("🔍", "追踪", "[dim]未启用[/dim]")

    # ★ 会话 ID（便于 /thread-id 恢复）
    if thread_id:
        info.add_row("🆔", "会话", f"[dim]{thread_id}[/dim]")

    return info


def _build_welcome_hints():
    """底部操作提示。"""
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
    """打印精致启动屏。"""
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


def print_help() -> None:
    console.print(
        Panel(
            "[bold]可用命令[/bold]\n"
            "  /exit         退出\n"
            "  /help         显示帮助\n"
            "  /clear        清空当前会话状态\n"
            "  /skills       列出所有技能\n"
            "  /config       显示当前配置\n"
            "  /metrics      显示本次会话指标\n"
            "  /trace        查看最近的调用指标\n"
            "  /thinking     查看最近一次任务的思考过程\n"
            "  /cards        查看用户卡片（第 1 层记忆）\n"
            "  /recall <q>   检索历史会话（第 2 层记忆）\n"
            "  /memory       查看记忆后端状态\n"
            "  /learn        从历史轨迹提炼工程经验\n"
            "  /<skill-name> 加载 user-invoked 技能\n"
            "  其他输入       作为任务发送给 Agent",
            title="Help",
        )
    )


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
# 思考过程查询
# ============================================================


def _thinking_path(rt, thread_id: str) -> Path:
    """思考轨迹 JSONL 路径。"""
    d = rt.config.trajectory_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{thread_id}_thinking.jsonl"


def _save_thinking_trace(rt, thread_id: str, turns: list[dict]) -> None:
    """把每轮思考追加到 JSONL。"""
    path = _thinking_path(rt, thread_id)
    with open(path, "a", encoding="utf-8") as f:
        for turn in turns:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def show_thinking(rt, thread_id: str) -> None:
    """显示最近一次任务的思考过程。"""
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
    """返回检索器状态描述（不触发模型下载）。"""
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
# 会话结束钩子：提炼卡片 + 生成会话摘要
# ============================================================


def _do_extraction(rt, thread_id: str) -> None:
    """同步执行提炼（被异步线程 / 启动补提炼调用）。"""
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

        # 1. 提炼卡片
        if os.getenv("AGENT_USER_MEMORY", "true").lower() == "true":
            try:
                extract_and_save(llm, messages, session_id=thread_id)
            except Exception as e:
                log.warning("card_extraction_failed", error=str(e))

        # 2. 生成会话摘要
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
                        log.warning(
                            "retriever_index_failed",
                            error=str(idx_err),
                        )
            except Exception as e:
                log.warning("session_summary_failed", error=str(e))

        remove_pending(rt.config.meta_dir, thread_id)

    except Exception as e:
        log.warning("extraction_failed", error=str(e))


def extract_and_save_memory_async(rt, thread_id: str) -> None:
    """会话结束时异步提炼（写 pending + daemon 线程 + 最多等 1s）。"""
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
    """启动时检查 pending 任务，后台补跑。"""
    try:
        meta_dir = rt.config.meta_dir
        tasks = load_pending(meta_dir)
        if not tasks:
            return

        to_process = [t for t in tasks if t.thread_id != current_thread_id]
        if not to_process:
            return

        console.print(f"[dim]发现 {len(to_process)} 个待提炼会话，后台补跑…[/dim]")

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
# /learn 命令
# ============================================================


def learn_from_trajectories(rt) -> None:
    try:
        from memory.lesson_extractor import (
            extract_lessons_from_trajectories,
            merge_into_lessons,
        )
    except ImportError:
        console.print("[yellow]lesson_extractor 未安装，跳过[/yellow]")
        return

    traj_dir = rt.config.trajectory_dir

    from agent.core import _build_compaction_llm

    llm = _build_compaction_llm(rt.config)

    console.print("[dim]正在分析最近的成功轨迹…[/dim]")
    extracted = extract_lessons_from_trajectories(llm, traj_dir)

    if not extracted:
        console.print("[dim]未找到可提炼的成功轨迹[/dim]")
        return

    merge_into_lessons(rt.config.meta_dir, extracted)
    console.print(f"[dim]工程经验已更新: {rt.config.meta_dir / 'memory' / 'lessons.md'}[/dim]")


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
    """从一个 tool_call / tool_call_chunk 里提取工具名。"""
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
    """流式执行任务，把每一轮的 content / reasoning / tool_calls 单独记录。

    设计：
    - 每一轮 LLM 输出（可能带工具调用）单独存进 `turns`
    - 实时显示**只展示当前轮次**的思考，不拼接历史
    - 结束后把全部轮次写 JSONL（`/thinking` 可查询）
    - 返回值是**最后一轮非空的 content**（最终答案）

    Returns:
        最终答案文本（可能为空字符串）。
    """
    turns: list[dict] = []
    cur_content: list[str] = []
    cur_reasoning: list[str] = []
    cur_tool_calls: list[str] = []

    # 实时显示缓冲（仅当前轮次）
    reasoning_display: list[str] = []
    tool_events: list[str] = []
    tool_seen: set[str] = set()
    _last_update = [0.0]

    REASONING_DISPLAY_MAX = 800
    TOOL_DISPLAY_MAX = 6

    def seal_round() -> None:
        """结束当前轮次，存进 turns，重置缓冲区。"""
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

        # 工具事件（历史，跨轮次）
        if tool_events:
            for line in tool_events[-TOOL_DISPLAY_MAX:]:
                t.append(line + "\n", style="cyan")
            t.append("\n")

        # 当前轮次的 reasoning
        reasoning = "".join(reasoning_display)
        if reasoning:
            if len(reasoning) > REASONING_DISPLAY_MAX:
                reasoning = "… " + reasoning[-REASONING_DISPLAY_MAX:]
            t.append("💭 思考中…\n", style="dim italic")
            t.append(reasoning, style="dim")
            t.append("\n\n")

        # 当前轮次的 content（只显示本轮的，不拼历史）
        cur = "".join(cur_content)
        if cur:
            t.append(cur)

        return t

    live = Live(
        build_display(),
        console=console,
        refresh_per_second=4,
        transient=True,
        vertical_overflow="visible",
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
                # 收集工具调用信号（tool_call_chunks 是流式的，可能分片到达）
                tcc = getattr(msg, "tool_call_chunks", None) or []
                for tc in tcc:
                    name = _extract_tool_name(tc)
                    if name and name not in cur_tool_calls:
                        cur_tool_calls.append(name)

                # 兜底：有些 provider 直接给 tool_calls
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
                # 工具返回 → 结束当前轮次
                name = getattr(msg, "name", "tool") or "tool"
                if name not in tool_seen:
                    tool_seen.add(name)
                    tool_events.append(f"  ⚙ {name} ✓")

                seal_round()
                reasoning_display.clear()

            now = time.time()
            if now - _last_update[0] > 0.25:
                live.update(build_display())
                _last_update[0] = now

        # 流结束：把最后一轮收进去
        seal_round()
        live.update(build_display())

    # ---------- 持久化全部轮次 ----------
    try:
        _save_thinking_trace(rt, thread_id, turns)
    except Exception as e:
        log.warning("save_thinking_trace_failed", error=str(e))

    # ---------- 返回最终答案 ----------
    for turn in reversed(turns):
        if turn["content"]:
            return _dedup_repeats(turn["content"])
    return ""


# ============================================================
# 单次任务 / 交互模式
# ============================================================


def _print_final(content: str, rt, thread_id: str, turns_count: int) -> None:
    """统一打印最终答案 + 思考过程提示。"""
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
    try:
        content = stream_task_with_reasoning(rt, task, thread_id)
        display.flush()

        # 从 thinking JSONL 里数一下轮数
        turns_count = 0
        try:
            path = _thinking_path(rt, thread_id)
            if path.exists():
                lines = path.read_text(encoding="utf-8").strip().split("\n")
                # 只数最后一段（round 从 1 重新开始的）
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

        if lower_input in ("/exit", "/quit", "exit", "quit"):
            console.print("[dim]再见[/dim]")
            break
        if lower_input in ("/help", "help"):
            print_help()
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
            show_metrics(rt)
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
        if lower_input == "/learn":
            learn_from_trajectories(rt)
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

        # 绑定上下文（含 trace_id）
        bind_context(
            session_id=rt.config.project_path.name,
            thread_id=thread_id,
            trace_id=get_trace_id(),
        )

        try:
            console.print()
            content = stream_task_with_reasoning(rt, task_text, thread_id)
            display.flush()

            # 数轮数
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

    # ★ 静音第三方库日志（httpx / mcp / openai 等）
    _silence_noisy_loggers()

    # 生成 trace_id
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

    # ★ trace_id 写进日志上下文，屏幕不显示
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

    # 启动时补跑 pending 提炼
    try:
        process_pending_on_startup(rt, thread_id)
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
        # 异步提炼，不阻塞退出
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