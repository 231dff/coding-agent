"""Day 28: 评测任务定义。

每个评测任务包含：
- 任务描述
- 初始工作区文件
- 成功判定函数
- 期望工具序列（可选）
- token 预算
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EvalTask:
    """一个评测任务。"""

    id: str
    category: str  # single_file | multi_file | bug_fix | dep_upgrade
    description: str
    setup: dict[str, str]  # path -> content
    success_assert: str  # Python 代码块，最后一行作为结果表达式
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
            tasks.append(
                EvalTask(
                    id=item["id"],
                    category=item.get("category", data.get("category", "misc")),
                    description=item["description"],
                    setup=item.get("setup", {}),
                    success_assert=item["success_assert"],
                    expected_tools=item.get("expected_tools", []),
                    token_budget=item.get("token_budget", 10000),
                    max_iterations=item.get("max_iterations", 10),
                    tags=item.get("tags", []),
                )
            )

    return tasks


# 允许断言使用的内置函数白名单（安全 + 够用）
_SAFE_BUILTINS = {
    # 类型
    "bool": bool, "int": int, "float": float, "str": str,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    # 聚合
    "all": all, "any": any, "len": len, "min": min, "max": max,
    "sum": sum, "sorted": sorted, "reversed": reversed,
    "enumerate": enumerate, "zip": zip, "range": range, "map": map,
    "filter": filter,
    # 对象
    "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
    "repr": repr, "type": type,
    # 数学
    "abs": abs, "round": round, "pow": pow,
    # 调试
    "print": print,
    # 异常
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    # 常用
    "True": True, "False": False, "None": None,
}


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.split("\n"))


def _wrap_result(result, expr: str) -> tuple[bool, str]:
    """把 eval 的结果包装成 (bool, error_msg)。"""
    if result:
        return True, ""
    return False, (
        f"❌ 断言结果为 False（Agent 输出不符合预期）\n"
        f"  断言:\n{_indent(expr, 2)}"
    )


def run_assert(assert_expr: str, workspace: Path) -> tuple[bool, str]:
    """在 workspace 上下文中执行断言。

    支持三种写法：

    1) 单表达式：
        success_assert: '"return a + b" in (ws / "calc.py").read_text()'

    2) 跨多行的单个表达式（AST 自动识别）：
        success_assert: |
          "range(len(xs) - 1)" not in (ws / "calc.py").read_text() and (
              "range(len(xs))" in (ws / "calc.py").read_text()
          )

    3) 多行代码块，最后一行是表达式：
        success_assert: |
          _content = (ws / "calc.py").read_text()
          "range(len(xs) - 1)" not in _content and "range(len(xs))" in _content

    实现要点：
    - 用 AST 区分语句和最后的表达式
    - ★ globals 和 locals 用同一个 dict，避免生成器表达式 / 推导式
      在分离的 locals 里查不到名字（Python 已知坑）
    """
    if not assert_expr or not assert_expr.strip():
        return False, "❌ success_assert 为空"

    # ★ 关键：ws 和 __builtins__ 都放进 globals，
    #   并用同一个 dict 作为 globals / locals
    namespace: dict = {
        "__builtins__": _SAFE_BUILTINS,
        "ws": workspace,
    }

    # ---------- 用 AST 解析，区分语句和最后的表达式 ----------
    try:
        tree = ast.parse(assert_expr)
    except SyntaxError as e:
        return False, (
            f"❌ 断言语法错误（YAML 里的 success_assert 本身写错了）\n"
            f"  错误: {e}\n"
            f"  代码:\n{_indent(assert_expr, 2)}"
        )

    if not tree.body:
        return False, "❌ success_assert 为空"

    *body_stmts, last_stmt = tree.body

    # 1. 执行前面的所有语句（赋值、import 等）
    if body_stmts:
        module = ast.Module(body=body_stmts, type_ignores=[])
        try:
            code_body = compile(module, "<assert>", "exec")
            exec(code_body, namespace)  # noqa: S102  ← locals 省略 = 用 globals
        except SyntaxError as e:
            return False, (
                f"❌ 断言代码块语法错误（前 {len(body_stmts)} 行）\n"
                f"  错误: {e}\n"
                f"  代码:\n{_indent(assert_expr, 2)}"
            )
        except NameError as e:
            return False, (
                f"❌ 断言代码块里用了不在白名单里的名字\n"
                f"  错误: {e}\n"
                f"  提示: 只允许用 ws、len/all/any/str/int 等常用函数"
            )
        except Exception as e:
            return False, (
                f"❌ 断言代码块执行异常: {type(e).__name__}: {e}\n"
                f"  代码:\n{_indent(assert_expr, 2)}"
            )

    # 2. 处理最后一条语句
    if isinstance(last_stmt, ast.Expr):
        # 最后一行是表达式 → eval 它，值作为断言结果
        expr = ast.Expression(body=last_stmt.value)
        try:
            code_expr = compile(expr, "<assert>", "eval")
            result = eval(code_expr, namespace)  # noqa: S307  ← 只传 globals
        except SyntaxError as e:
            return False, (
                f"❌ 断言语法错误\n"
                f"  错误: {e}\n"
                f"  代码:\n{_indent(assert_expr, 2)}"
            )
        except NameError as e:
            return False, (
                f"❌ 断言里用了不在白名单里的名字\n"
                f"  错误: {e}\n"
                f"  提示: 只允许用 ws、len/all/any/str/int 等常用函数"
            )
        except Exception as e:
            return False, (
                f"❌ 断言执行失败: {type(e).__name__}: {e}\n"
                f"  代码:\n{_indent(assert_expr, 2)}"
            )
        return _wrap_result(result, assert_expr)

    # 3. 最后一行也是语句（比如 `_result = ...`）→ 检查 _result 变量
    try:
        module = ast.Module(body=[last_stmt], type_ignores=[])
        code_last = compile(module, "<assert>", "exec")
        exec(code_last, namespace)  # noqa: S102
    except Exception as e:
        return False, (
            f"❌ 断言最后一行执行异常: {type(e).__name__}: {e}\n"
            f"  代码:\n{_indent(assert_expr, 2)}"
        )

    # 约定：如果没有返回表达式，检查 _result 变量
    result = namespace.get("_result", False)
    if result:
        return True, ""
    return False, (
        f"❌ 断言失败（最后一行不是表达式，且 _result 变量为假）\n"
        f"  代码:\n{_indent(assert_expr, 2)}\n"
        f"  提示: 最后一行应该是表达式，或把结果赋给 _result 变量"
    )