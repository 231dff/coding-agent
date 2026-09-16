"""终端指标显示。

从 MetricsMiddleware 的队列消费事件，攒起来，由主流程在合适时机 flush，
避免与 Rich Live 抢 Console 导致输出重复。
"""
from __future__ import annotations

import queue
import threading
from typing import Any

from rich.console import Console
from rich.text import Text


DIM = "grey54"


def _fmt_llm(event: dict) -> Text:
    model = event.get("model", "?")
    in_tok = event.get("input_tokens", 0)
    out_tok = event.get("output_tokens", 0)
    cache = event.get("cache_read", 0)
    dur = event.get("duration_s", 0)
    cost = event.get("cost_usd", 0)

    t = Text()
    t.append("  ⚡ ", style="yellow")
    t.append(f"{model}", style=f"{DIM} bold")
    t.append("  in ", style=DIM)
    t.append(f"{in_tok}", style=DIM)
    t.append(" · out ", style=DIM)
    t.append(f"{out_tok}", style=DIM)
    if cache:
        t.append(" · cache ", style=DIM)
        t.append(f"{cache}", style="green")
    t.append(f" · {dur}s", style=DIM)
    t.append(f" · ${cost:.5f}", style=DIM)
    return t


def _fmt_tool(event: dict) -> Text:
    tool = event.get("tool", "?")
    dur = event.get("duration_s", 0)
    ok = event.get("success", True)

    t = Text()
    t.append("  🔧 ", style="blue")
    t.append(f"{tool}", style=f"{DIM} bold")
    t.append(f"  {dur}s", style=DIM)
    t.append("  ✓" if ok else "  ✗", style="green" if ok else "red")
    return t


class MetricsDisplay:
    """后台线程消费 metrics 队列，攒起来，主流程调 flush() 时才打印。

    为什么不在 _run 里直接 print：
    - Rich Live 会持续重绘；如果此时另一个线程 print，会打断 Live，
      导致内容被反复重打（就是"回答重复十几遍"的原因）。
    - 改为缓存 + 主动 flush，Live 期间绝对不打印，输出干净。
    """

    def __init__(self, metrics_queue: "queue.Queue[dict] | None", console: Console):
        self.queue = metrics_queue
        self.console = console
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.history: list[dict] = []
        self._history_lock = threading.Lock()
        # 待渲染的事件
        self._pending: list[dict] = []
        self._pending_lock = threading.Lock()

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self.queue is None:
            return
        self._thread = threading.Thread(
            target=self._run, name="metrics-display", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---------- 内部 ----------

    def _run(self) -> None:
        """只负责收集，不打印。"""
        while not self._stop.is_set():
            try:
                event = self.queue.get(timeout=0.2)  # type: ignore[union-attr]
            except queue.Empty:
                continue
            except Exception:
                break

            with self._history_lock:
                self.history.append(event)
                if len(self.history) > 500:
                    self.history = self.history[-500:]

            with self._pending_lock:
                self._pending.append(event)

    def _render(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "llm":
            self.console.print(_fmt_llm(event))
        elif etype == "tool":
            self.console.print(_fmt_tool(event))

    # ---------- 主动 flush（主流程调用）----------

    def flush(self) -> None:
        """把攒下的 pending 事件一次性打印。Live 结束后调用。"""
        with self._pending_lock:
            events = self._pending
            self._pending = []

        for e in events:
            try:
                self._render(e)
            except Exception:
                pass

    # ---------- /trace 命令用 ----------

    def dump_recent(self, n: int = 30) -> None:
        with self._history_lock:
            items = self.history[-n:]

        if not items:
            self.console.print(f"[{DIM}]暂无指标记录[/]")
            return

        total_cost = sum(
            e.get("cost_usd", 0) for e in items if e.get("type") == "llm"
        )
        llm_count = sum(1 for e in items if e.get("type") == "llm")
        tool_count = sum(1 for e in items if e.get("type") == "tool")

        self.console.print(
            f"[{DIM}]── 最近 {len(items)} 条指标 · "
            f"{llm_count} 次模型调用 · {tool_count} 次工具 · "
            f"累计 ${total_cost:.5f} ──[/]"
        )
        for e in items:
            try:
                self._render(e)
            except Exception:
                pass