"""Human-in-the-Loop 规划工具。

Agent 遇到复杂任务时调用 `propose_plan`，向用户展示 2-4 个候选策略，
等用户选择后再执行。避免「规划好了直接执行」导致方向偏差。

关键：使用 rich Console 输出，避免被 main.py 的 Live 覆盖。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from langchain.tools import tool
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

# ★ 用独立的 Console，避免和 main.py 的 Live 冲突
_console = Console(stderr=False, highlight=False)


def _is_interactive() -> bool:
    """判断当前是否在可交互的 CLI 环境。

    不依赖 isatty（rich 环境下容易误判），
    改看环境变量 + 是否被显式禁用。
    """
    if os.getenv("AGENT_INTERACTIVE_PLANNING", "true").lower() != "true":
        return False
    # eval 模式禁用
    if os.getenv("AGENT_EVAL_MODE", "false").lower() == "true":
        return False
    return True


def _render_plans_table(plans: list[dict[str, Any]]) -> Table:
    """渲染方案列表为 rich Table。"""
    table = Table(show_header=True, box=None, padding=(0, 2), expand=False)
    table.add_column("#", style="bold cyan", width=3)
    table.add_column("方案", style="bold white")
    table.add_column("说明")
    table.add_column("优点", style="green")
    table.add_column("缺点", style="red")

    for i, p in enumerate(plans, 1):
        table.add_row(
            str(i),
            p.get("name", f"方案 {i}"),
            p.get("description", ""),
            " · ".join(p.get("pros", []) or []),
            " · ".join(p.get("cons", []) or []),
        )
    return table


@tool
def propose_plan(plans_json: str) -> str:
    """向用户展示 2-4 个候选实现策略，等用户选择后再执行。

    **只在任务较复杂时调用**（涉及 ≥3 个文件、或 ≥2 个技术决策、
    或存在多种明显不同的实现路径）。简单任务（改一个文件、查一个问题）不要用。

    调用后，用户的回答会作为工具结果返回。你需要严格按用户选择的方案执行。

    Args:
        plans_json: JSON 数组字符串，每项格式：
            [
              {
                "name": "最小可用版",
                "description": "3 个 Agent + 4 个工具，单文件 main.py",
                "pros": ["跑得快", "好理解"],
                "cons": ["无异常处理"]
              }
            ]

    Returns:
        JSON 字符串：{"selected_index": 1, "selected_name": "...",
                     "custom_instruction": "(用户自定义时填写)"}
    """
    # 1. 解析方案
    try:
        plans = json.loads(plans_json)
    except json.JSONDecodeError as e:
        return json.dumps(
            {"error": f"plans_json 解析失败: {e}"}, ensure_ascii=False
        )

    if not isinstance(plans, list) or not plans:
        return json.dumps({"error": "plans_json 必须是非空数组"}, ensure_ascii=False)

    if len(plans) > 4:
        plans = plans[:4]

    # 2. 非交互模式 → 自动选第一个
    if not _is_interactive():
        selected = plans[0]
        return json.dumps(
            {
                "selected_index": 1,
                "selected_name": selected.get("name", ""),
                "custom_instruction": "",
                "auto_selected": True,
                "reason": "非交互环境，自动采用第一个方案",
            },
            ensure_ascii=False,
        )

    # 3. 交互模式 → 用 rich 渲染 + Prompt.ask（不会被 Live 覆盖）
    _console.print()
    _console.print(Panel(
        "🤔 Agent 提供了多个实现策略，请选择",
        border_style="bright_cyan",
        expand=False,
    ))
    _console.print(_render_plans_table(plans))
    _console.print(
        "[dim]输入 [bold cyan]1[/bold cyan]-[bold cyan]{}[/bold cyan] 选择方案，"
        "或直接输入自定义要求（比如「方案 2，但不要 Dockerfile」）[/dim]".format(len(plans))
    )

    timeout_s = int(os.getenv("AGENT_PLAN_TIMEOUT", "300"))
    deadline = time.time() + timeout_s

    while True:
        remaining = int(deadline - time.time())
        if remaining <= 0:
            _console.print(f"[yellow]⏱ 超时（{timeout_s}s），自动选择方案 [1][/yellow]")
            selected = plans[0]
            return json.dumps(
                {
                    "selected_index": 1,
                    "selected_name": selected.get("name", ""),
                    "custom_instruction": "",
                    "auto_selected": True,
                    "reason": "用户响应超时",
                },
                ensure_ascii=False,
            )

        try:
            # ★ 用 rich.Prompt.ask，专门适配 rich 环境
            raw = Prompt.ask(
                f"[bold cyan]你的选择[/bold cyan] [dim](剩余 {remaining}s)[/dim]",
                console=_console,
                default="",
                show_default=False,
            ).strip()
        except (KeyboardInterrupt, EOFError):
            _console.print("[yellow]⚠ 用户中断，采用方案 [1][/yellow]")
            selected = plans[0]
            return json.dumps(
                {
                    "selected_index": 1,
                    "selected_name": selected.get("name", ""),
                    "custom_instruction": "",
                    "auto_selected": True,
                    "reason": "用户中断",
                },
                ensure_ascii=False,
            )

        if not raw:
            continue

        # 用户输入纯数字 → 选择方案
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(plans):
                selected = plans[idx - 1]
                _console.print(
                    f"[green]✓ 已选择方案 [{idx}] {selected.get('name', '')}[/green]"
                )
                return json.dumps(
                    {
                        "selected_index": idx,
                        "selected_name": selected.get("name", ""),
                        "custom_instruction": "",
                    },
                    ensure_ascii=False,
                )
            else:
                _console.print(
                    f"[red]⚠ 请输入 1-{len(plans)} 之间的数字[/red]"
                )
                continue

        # 用户输入其他内容 → 视为自定义要求
        _console.print(f"[green]✓ 已记录自定义要求：[/green]{raw}")
        return json.dumps(
            {
                "selected_index": 1,
                "selected_name": plans[0].get("name", ""),
                "custom_instruction": raw,
                "interpreted_as": "用户自定义，以第一个方案为基础，加入以下要求",
            },
            ensure_ascii=False,
        )


PLANNING_TOOLS = ["propose_plan"]
