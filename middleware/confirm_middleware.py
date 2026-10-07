"""交互式确认中间件。

在关键工具调用前暂停，让用户确认。

设计：
  - 只对「写操作」和「危险命令」触发
  - 用户可选：y（本次允许）/ a（本次会话全部允许该工具）/ n（拒绝）
  - 非交互模式自动允许
  - 环境变量 AGENT_CONFIRM=off 可整体关闭

修复记录（2026-10-07）：
  - awrap_tool_call 之前直接调用同步版 wrap_tool_call，
    导致 async handler 返回的 coroutine 没被 await → ToolMessage 变 coroutine。
    现在拆出 _handle 内部逻辑，同步/异步各自正确 await/调用。
"""

from __future__ import annotations

import inspect
import os
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

_console = Console(stderr=False, highlight=False)


# 触发确认的工具
CONFIRM_TOOLS = {
    "write_file",
    "edit_file",
    "apply_patch",
    "sandbox_write",
    "execute",
    "run_tests",
}

# execute 里危险命令的关键词（只对这些问，普通 execute 不问）
DANGEROUS_CMD_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bdocker\s+rm\b",
    r"\bpip\s+uninstall\b",
    r"\bchmod\s+777\b",
    r"\bsudo\b",
]

_exec_dangerous = [re.compile(p) for p in DANGEROUS_CMD_PATTERNS]


class ConfirmMiddleware(AgentMiddleware):
    """关键工具调用前确认。"""

    name: str = "ConfirmMiddleware"

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled
        self._allow_all = False
        self._allow_tools: set[str] = set()

    # ---------- 同步 ----------

    def wrap_tool_call(self, request, handler):
        rejection = self._maybe_reject(request)
        if rejection is not None:
            return rejection
        return handler(request)

    # ---------- 异步 ----------

    async def awrap_tool_call(self, request, handler):
        rejection = self._maybe_reject(request)
        if rejection is not None:
            return rejection

        # handler 可能是 async callable，也可能返回 awaitable
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
        return result

    # ---------- 内部：共用逻辑 ----------

    def _maybe_reject(self, request):
        """用户拒绝时返回 error ToolMessage；同意时返回 None。"""
        if not self._should_ask(request):
            return None

        allowed = self._ask_user(request)
        if allowed:
            return None

        tc = getattr(request, "tool_call", None) or {}
        tool_name = tc.get("name", "?")
        tool_id = tc.get("id", "")
        return ToolMessage(
            content=f"[用户拒绝] 用户拒绝执行 {tool_name}",
            tool_call_id=tool_id,
            status="error",
        )

    def _should_ask(self, request) -> bool:
        if not self.enabled or self._allow_all:
            return False

        if os.getenv("AGENT_EVAL_MODE", "false").lower() == "true":
            return False
        if os.getenv("AGENT_CONFIRM", "on").lower() == "off":
            return False

        tc = getattr(request, "tool_call", None) or {}
        name = tc.get("name", "")
        args = tc.get("args", {}) or {}

        if name in self._allow_tools:
            return False

        if name not in CONFIRM_TOOLS:
            return False

        if name == "execute":
            cmd = args.get("command", "")
            if not any(p.search(cmd) for p in _exec_dangerous):
                return False

        return True

    def _ask_user(self, request) -> bool:
        tc = getattr(request, "tool_call", None) or {}
        name = tc.get("name", "?")
        args = tc.get("args", {}) or {}

        lines = []
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > 200:
                v_str = v_str[:200] + " ..."
            lines.append(f"  [dim]{k}:[/dim] [white]{v_str}[/white]")

        _console.print()
        _console.print(
            Panel(
                f"[bold yellow]⚠ 即将执行:[/bold yellow] [bold]{name}[/bold]\n\n"
                + "\n".join(lines),
                border_style="yellow",
                expand=False,
            )
        )
        _console.print(
            "[dim]选择: [bold green]y[/bold green]=允许  "
            "[bold cyan]a[/bold cyan]=本次会话全部允许该工具  "
            "[bold red]n[/bold red]=拒绝[/dim]"
        )

        try:
            ans = (
                Prompt.ask(
                    "[bold cyan]确认[/bold cyan]",
                    console=_console,
                    choices=["y", "a", "n"],
                    default="y",
                )
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            return False

        if ans == "a":
            self._allow_tools.add(name)
            return True
        return ans == "y"


def create_confirm_middleware(enabled: bool = True) -> ConfirmMiddleware:
    return ConfirmMiddleware(enabled=enabled)
