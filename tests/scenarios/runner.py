"""Day 5: 10 个多样化任务的冒烟测试运行器。

每个场景定义：任务描述、前置文件、成功断言、token 预算。
统计成功率与失败模式，输出 M1 报告。
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent.config import AgentConfig
from agent.core import build_agent


@dataclass
class Scenario:
    name: str
    task: str
    setup: dict[str, str]  # path -> content，前置创建的文件
    assert_fn: Callable[[Path], bool]
    expected_tool_calls: int = 8
    token_budget: int = 4000


def _fix_bug_assert(ws: Path) -> bool:
    return "return a + b" in (ws / "calc.py").read_text()


def _rename_assert(ws: Path) -> bool:
    c = (ws / "util.py").read_text()
    return "new_name" in c and "old_name" not in c


def _add_comment_assert(ws: Path) -> bool:
    c = (ws / "calc.py").read_text()
    return "#" in c and "return a + b" in c


def _multi_edit_assert(ws: Path) -> bool:
    a = (ws / "a.py").read_text()
    b = (ws / "b.py").read_text()
    return "VALUE = 42" in a and "from a import VALUE" in b


def _search_and_edit_assert(ws: Path) -> bool:
    c = (ws / "config.py").read_text()
    return "DEBUG = False" in c


SCENARIOS: list[Scenario] = [
    Scenario(
        name="fix_bug",
        task="calc.py 的 add 函数返回值有 bug，请读取并修复。",
        setup={"calc.py": "def add(a, b):\n    return a - b\n"},
        assert_fn=_fix_bug_assert,
    ),
    Scenario(
        name="rename_function",
        task="把 util.py 里的 old_name 重命名为 new_name。",
        setup={"util.py": "def old_name():\n    return 42\n"},
        assert_fn=_rename_assert,
    ),
    Scenario(
        name="add_comment",
        task="给 calc.py 的 add 函数添加一行注释说明用途。",
        setup={"calc.py": "def add(a, b):\n    return a + b\n"},
        assert_fn=_add_comment_assert,
    ),
    Scenario(
        name="multi_file_edit",
        task="a.py 中定义 VALUE = 42，b.py 中当前是 VALUE = 0，请让 b.py 从 a.py 导入 VALUE。",
        setup={
            "a.py": "VALUE = 42\n",
            "b.py": "VALUE = 0\n",
        },
        assert_fn=_multi_edit_assert,
        expected_tool_calls=12,
    ),
    Scenario(
        name="search_and_edit",
        task="在 config.py 中把 DEBUG 的值改为 False。",
        setup={"config.py": "DEBUG = True\nLOG_LEVEL = 'info'\n"},
        assert_fn=_search_and_edit_assert,
    ),
    Scenario(
        name="read_nonexistent",
        task="读取 missing.py，如果不存在就告诉我。",
        setup={},
        assert_fn=lambda ws: True,  # 只验证不崩溃
        expected_tool_calls=3,
    ),
    Scenario(
        name="edit_conflict_recovery",
        task="app.py 里有多处 return x，把 process_a 函数中的 return x 改成 return y。",
        setup={
            "app.py": (
                "def process_a():\n    return x\n\n"
                "def process_b():\n    return x\n\n"
                "def process_c():\n    return x\n"
            )
        },
        assert_fn=lambda ws: "return y" in (ws / "app.py").read_text(),
        expected_tool_calls=10,
    ),
    Scenario(
        name="glob_and_read",
        task="找到所有 .py 文件，告诉我最大的那个的文件名。",
        setup={"a.py": "x = 1\n", "b.py": "y = 2\n" * 100, "c.py": "z = 3\n"},
        assert_fn=lambda ws: True,
        expected_tool_calls=6,
    ),
    Scenario(
        name="grep_and_report",
        task="搜索所有包含 TODO 的行，报告在哪些文件里。",
        setup={"one.py": "# TODO: fix\nx = 1\n", "two.py": "# TODO: refactor\ny = 2\n"},
        assert_fn=lambda ws: True,
        expected_tool_calls=6,
    ),
    Scenario(
        name="no_op_task",
        task="告诉我当前工作区有哪些文件。",
        setup={"main.py": "pass\n", "README.md": "# Test\n"},
        assert_fn=lambda ws: True,
        expected_tool_calls=3,
    ),
]


def run_all(model: str = "openai:qwen3.8-max-0902") -> dict:
    import shutil
    import tempfile

    results = []
    for sc in SCENARIOS:
        ws = Path(tempfile.mkdtemp(prefix=f"scenario_{sc.name}_"))
        for path, content in sc.setup.items():
            (ws / path).write_text(content)

        cfg = AgentConfig(workspace=str(ws), model=model, verbose=False)
        agent = build_agent(cfg)

        start = time.time()
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": sc.task}]},
                config={"configurable": {"thread_id": f"smoke-{sc.name}"}},
            )
            elapsed = time.time() - start
            tool_calls = sum(
                1 for m in result["messages"] if hasattr(m, "tool_calls") and m.tool_calls
            )
            passed = sc.assert_fn(ws)
            error = None
        except Exception as e:
            elapsed = time.time() - start
            tool_calls = -1
            passed = False
            error = str(e)

        results.append(
            {
                "name": sc.name,
                "passed": passed,
                "tool_calls": tool_calls,
                "elapsed_s": round(elapsed, 2),
                "error": error,
            }
        )
        shutil.rmtree(ws, ignore_errors=True)

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    report = {
        "model": model,
        "total": total,
        "passed": passed_count,
        "success_rate": round(passed_count / total, 3),
        "details": results,
    }
    return report


if __name__ == "__main__":
    report = run_all()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    report_path = Path("docs/m1_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n成功率: {report['passed']}/{report['total']} ({report['success_rate']:.0%})")
