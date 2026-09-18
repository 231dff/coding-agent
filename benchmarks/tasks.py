"""基准任务定义。

每个任务包含：
- name：任务名
- description：给 Agent 的输入
- setup：可选，创建测试环境
- timeout：超时秒数
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class BenchTask:
    """一个基准任务。"""

    name: str
    description: str
    timeout: int = 120
    setup: Callable[[Path], None] | None = None
    verify: Callable[[Path], bool] | None = None
    tags: list[str] = field(default_factory=list)


def _setup_calc(ws: Path) -> None:
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n")


def _setup_utils(ws: Path) -> None:
    (ws / "utils.py").write_text("def old_name():\n    return 42\n")


def _verify_calc_has_docstring(ws: Path) -> bool:
    content = (ws / "calc.py").read_text()
    return '"""' in content


def _verify_renamed(ws: Path) -> bool:
    content = (ws / "utils.py").read_text()
    return "new_name" in content and "old_name" not in content


# ============================================================
# 任务清单
# ============================================================

TASKS: list[BenchTask] = [
    BenchTask(
        name="read_only",
        description="读一下 README",
        timeout=30,
        tags=["simple", "read"],
    ),
    BenchTask(
        name="read_file",
        description="读取 calc.py 的内容",
        timeout=30,
        setup=_setup_calc,
        tags=["simple", "read"],
    ),
    BenchTask(
        name="add_docstring",
        description="给 calc.py 的 add 函数添加 docstring",
        timeout=60,
        setup=_setup_calc,
        verify=_verify_calc_has_docstring,
        tags=["write", "edit"],
    ),
    BenchTask(
        name="rename_function",
        description="把 utils.py 里的 old_name 重命名为 new_name",
        timeout=60,
        setup=_setup_utils,
        verify=_verify_renamed,
        tags=["write", "rename"],
    ),
]


def get_task(name: str) -> BenchTask | None:
    for t in TASKS:
        if t.name == name:
            return t
    return None
