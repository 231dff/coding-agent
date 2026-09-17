"""Agent CLI 入口。

用法：
    coding-agent init [--project PATH]
    coding-agent [--project PATH] [--model MODEL] [task]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
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
from memory.session_summary import (
    session_summary_repo,
    summarize_session,
)
from memory.store import (
    current_user_id,
    store_backend_info,
)
from observability.logger import bind_context, configure_logging, get_logger
from observability.metrics_display import MetricsDisplay
from observability.tracing import configure as configure_tracing
from observability.tracing import is_enabled, status_text

console = Console()
log = get_logger("main")


BANNER = """[bold cyan]
  ╔══════════════════════════════════════════════╗
  ║           Coding Agent                        ║
  ║  对任意项目进行代码理解、修改与测试           ║
  ╚══════════════════════════════════════════════╝
[/bold cyan]"""


# ============================================================
# 默认 thread_id：按项目路径生成稳定 ID（跨重启恢复）
# ============================================================


def _default_thread_id(project_path: Path) -> str:
    key = str(project_path.resolve())
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


# ============================================================
# 欢迎 / 帮助 / 配置
# ============================================================


def print_welcome(project_path: Path, rt) -> None:
    console.print(BANNER)
    console.print(f"[bold]项目:[/bold] {project_path}")

    cfg = rt.config
    console.print(f"[bold]模型:[/bold] {cfg.provider_id}/{cfg.model} [dim]({cfg.base_url})[/dim]")

    if rt.skill_registry:
        stats = rt.skill_registry.stats()
        console.print(
            f"[dim]技能: {stats['model_invoked']} 个自动调用, "
            f"{stats['user_invoked']} 个用户触发[/dim]"
        )

    # 记忆后端
    info = store_backend_info()
    console.print(f"[dim]记忆: {info.get('backend', '?')} ({info.get('type', '?')})[/dim]")

    if is_enabled():
        console.print(f"[dim]LangSmith: {status_text()}[/dim]")

    console.print("[dim]输入任务描述，Enter 发送。输入 /help 查看命令。[/dim]\n")


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
# 记忆相关命令
# ============================================================


def show_cards() -> None:
    """展示当前用户的卡片（第 1 层）。"""
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
    """检索历史会话（第 2 层）。"""
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
    """返回检索器状态描述。

    关键：不主动初始化检索器（避免触发模型下载）。
    只在缓存里已有实例时展示详情，否则只显示配置。
    """
    kind = os.getenv("AGENT_RETRIEVER", "bm25").lower()

    # BM25 无需展示细节
    if kind == "bm25":
        return "BM25（关键词）"

    # 看是否已有缓存的实例（避免触发初始化）
    try:
        from memory.retriever import _RETRIEVER_CACHE

        cache_key = f"{kind}:{user_id}"
        retriever = _RETRIEVER_CACHE.get(cache_key)
    except Exception:
        retriever = None

    if retriever is None:
        # 未初始化：只显示配置
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

    # 已有缓存实例：正常展示
    cls = type(retriever).__name__

    if cls == "HybridRetriever":
        if retriever.is_hybrid:
            return f"Hybrid（向量 {retriever.chroma.count()} 条 + BM25）"
        return f"Hybrid（降级：{retriever._chroma_error[:40]}）"

    if cls == "ChromaRetriever":
        try:
            return f"ChromaDB（{retriever.collection.count()} 条向量）"
        except Exception:
            return "ChromaDB"

    return f"{kind}（未知类型 {cls}）"


def show_memory_status() -> None:
    """显示记忆后端状态。"""
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

    # 检索器信息
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


def extract_and_save_memory(rt, thread_id: str) -> None:
    """会话结束时：
    1. 提炼用户卡片（第 1 层）
    2. 生成会话摘要（第 2 层的原始数据）
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = rt.agent.get_state(config)
        if state is None or not state.values:
            return

        messages = state.values.get("messages", [])
        if not messages or len(messages) < 4:
            return

        from agent.core import _build_compaction_llm

        llm = _build_compaction_llm(rt.config)

        user_id = current_user_id()
        project_path = str(rt.config.project_path)

        # ---------- 1. 提炼卡片 ----------
        if os.getenv("AGENT_USER_MEMORY", "true").lower() == "true":
            try:
                console.print("[dim]正在提炼用户卡片…[/dim]")
                added, skipped = extract_and_save(
                    llm,
                    messages,
                    session_id=thread_id,
                )
                if added:
                    console.print(f"[dim]新增 {added} 条卡片（跳过 {skipped} 条重复）[/dim]")
                else:
                    console.print("[dim]本次会话无新增卡片[/dim]")
            except Exception as e:
                log.warning("card_extraction_failed", error=str(e))

        # ---------- 2. 生成会话摘要 ----------
        if os.getenv("AGENT_RETRIEVAL", "true").lower() == "true":
            try:
                console.print("[dim]正在生成会话摘要…[/dim]")
                summary = summarize_session(
                    llm,
                    messages,
                    session_id=thread_id,
                    user_id=user_id,
                    project_path=project_path,
                )
                if summary and summary.summary:
                    # 写 Store（持久化）
                    session_summary_repo(user_id=user_id).add(summary)

                    # 同步索引到检索器
                    try:
                        from memory.retriever import get_retriever

                        get_retriever(user_id=user_id).index(summary)
                    except Exception as idx_err:
                        log.warning(
                            "retriever_index_failed",
                            error=str(idx_err),
                        )

                    console.print(f"[dim]会话摘要已保存（{summary.task_type}）[/dim]")
            except Exception as e:
                log.warning("session_summary_failed", error=str(e))

    except Exception as e:
        log.warning("memory_extraction_failed", error=str(e))


# ============================================================
# /learn 命令：从轨迹提炼工程经验（旧版功能保留）
# ============================================================


def learn_from_trajectories(rt) -> None:
    """从最近的轨迹里提炼工程经验（可选，独立于卡片系统）。"""
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


def _has_tool_call_signal(msg) -> bool:
    tcc = getattr(msg, "tool_call_chunks", None)
    if tcc:
        return True
    tc = getattr(msg, "tool_calls", None)
    if tc:
        return True
    return False


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
    """流式调用 Agent，实时展示 reasoning 和 content。

    关键设计：
    - 只用 stream_mode="messages"
    - 工具事件从 ToolMessage 取，按名字去重
    - pending_content 暂存当前轮，收到 ToolMessage 时按标记决定归属
    - 有 tool_calls 的轮次 content 不进最终结果
    """
    reasoning_buf: list[str] = []
    content_buf: list[str] = []
    pending_content: list[str] = []
    round_has_tool_call = [False]
    tool_seen: set[str] = set()
    tool_events: list[str] = []

    REASONING_DISPLAY_MAX = 1200
    TOOL_DISPLAY_MAX = 6
    _last_update = [0.0]

    def flush_round():
        if not round_has_tool_call[0] and pending_content:
            content_buf.extend(pending_content)
        pending_content.clear()
        round_has_tool_call[0] = False

    def current_display_text() -> str:
        parts = []
        if content_buf:
            parts.append("".join(content_buf))
        if not round_has_tool_call[0] and pending_content:
            parts.append("".join(pending_content))
        return "".join(parts)

    def build_display() -> Text:
        t = Text()
        if reasoning_buf:
            full = "".join(reasoning_buf)
            if len(full) > REASONING_DISPLAY_MAX:
                full = "… " + full[-REASONING_DISPLAY_MAX:]
            t.append("💭 思考中…\n", style="dim italic")
            t.append(full, style="dim")
            t.append("\n\n")
        if tool_events:
            for line in tool_events[-TOOL_DISPLAY_MAX:]:
                t.append(line + "\n", style="cyan")
            t.append("\n")
        text = current_display_text()
        if text:
            t.append(text)
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
                if _has_tool_call_signal(msg):
                    round_has_tool_call[0] = True

                c = _extract_content(msg)
                if c:
                    pending_content.append(c)

                r = _extract_reasoning(msg)
                if r:
                    reasoning_buf.append(r)

            elif isinstance(msg, ToolMessage):
                flush_round()

                name = getattr(msg, "name", "tool") or "tool"
                if name not in tool_seen:
                    tool_seen.add(name)
                    tool_events.append(f"  ⚙ {name} ✓")

            now = time.time()
            if now - _last_update[0] > 0.25:
                live.update(build_display())
                _last_update[0] = now

        flush_round()
        live.update(build_display())

    raw = "".join(content_buf)
    return _dedup_repeats(raw)


# ============================================================
# 单次任务 / 交互模式
# ============================================================


def run_single_task(rt, task: str, thread_id: str, display: MetricsDisplay) -> None:
    console.print(f"[bold green]任务:[/bold green] {task}\n")
    try:
        content = stream_task_with_reasoning(rt, task, thread_id)
        display.flush()
        console.print()
        console.print(Panel(Markdown(content), title="回复", border_style="cyan"))
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")
    except Exception as e:
        log.error("single_task_failed", error_type=type(e).__name__, error=str(e))
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

        # ---------- 内置命令 ----------
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

        # ---------- 记忆相关 ----------
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

        # ---------- 用户主动触发的 skill ----------
        task_text = user_input
        if user_input.startswith("/"):
            handled = handle_user_invoked_skill(rt, user_input)
            if handled is None:
                console.print(
                    f"[red]未知命令或技能: {user_input}[/red]\n[dim]输入 /help 查看命令[/dim]"
                )
                continue
            task_text = handled

        bind_context(
            session_id=rt.config.project_path.name,
            thread_id=thread_id,
        )

        try:
            console.print()
            content = stream_task_with_reasoning(rt, task_text, thread_id)
            display.flush()
            console.print()
            console.print(Panel(Markdown(content), border_style="cyan"))
            console.print()
        except KeyboardInterrupt:
            console.print("\n[yellow]已中断[/yellow]")
        except Exception as e:
            log.error("task_failed", error_type=type(e).__name__, error=str(e))
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

    console.print(f"[dim]正在启动 Agent (project={project_path})...[/dim]")
    console.print(f"[dim]会话 ID: {thread_id}[/dim]")

    try:
        rt = build_agent(cfg)
    except Exception as e:
        log.error("agent_start_failed", error_type=type(e).__name__, error=str(e))
        console.print(f"[red]Agent 启动失败: {type(e).__name__}: {e}[/red]")
        return 1

    display = MetricsDisplay(rt.metrics_queue, console)
    display.start()

    try:
        if parsed.task:
            run_single_task(rt, parsed.task, thread_id, display)
        else:
            print_welcome(project_path, rt)
            run_interactive(rt, thread_id, display)
    finally:
        # 会话结束钩子：提炼卡片 + 生成摘要
        try:
            extract_and_save_memory(rt, thread_id)
        except Exception:
            pass

        display.stop()
        rt.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
