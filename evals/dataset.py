"""Day 28: 评测任务定义。

每个评测任务包含：
- 任务描述
- 初始工作区文件
- 成功判定函数
- 期望工具序列（可选）
- token 预算
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class EvalTask:
    """一个评测任务。"""
    id: str
    category: str                # single_file | multi_file | bug_fix | dep_upgrade
    description: str
    setup: dict[str, str]        # path -> content
    success_assert: str          # Python 表达式，assert 语句
    expected_tools: list[str] = field(default_factory=list)
    token_budget: int = 10000
    max_iterations: int = 10
    tags: list[str] = field(default_factory=list)


def load_tasks(directory: str | Path) -> list[EvalTask]:
    """从 YAML 文件加载评测任务。"""
    directory = Path(directory)
    tasks: list[EvalTask] = []

    for yaml_file in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        for item in data.get("tasks", []):
            tasks.append(EvalTask(
                id=item["id"],
                category=item.get("category", data.get("category", "misc")),
                description=item["description"],
                setup=item.get("setup", {}),
                success_assert=item["success_assert"],
                expected_tools=item.get("expected_tools", []),
                token_budget=item.get("token_budget", 10000),
                max_iterations=item.get("max_iterations", 10),
                tags=item.get("tags", []),
            ))

    return tasks


def run_assert(assert_expr: str, workspace: Path) -> tuple[bool, str]:
    """在 workspace 上下文中执行断言表达式。

    assert_expr 是一个 Python 表达式字符串，例如：
        "return a + b" in (ws / "calc.py").read_text()
    """
    # 构造安全的执行环境
    import textwrap

    code = textwrap.dedent(f"""
        def _check(ws):
            return bool({assert_expr})
    """)

    env: dict = {}
    try:
        exec(code, {"__builtins__": __builtins__}, env)
        result = env["_check"](workspace)
        return result, ""
    except Exception as e:
        return False, f"断言执行失败: {type(e).__name__}: {e}"