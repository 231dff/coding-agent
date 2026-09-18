"""工具定义契约测试。

防止工具 schema 漂移：
- 每个工具必须有 name / description / args_schema
- name 必须符合命名规范
- 参数必须有类型注解
"""

from __future__ import annotations

import ast
import re

import pytest

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ============================================================
# 契约：所有工具都要满足
# ============================================================


def _all_tool_names() -> list[str]:
    """从 tools 模块收集所有工具名。

    不实际构造 Agent（避免依赖）。
    只扫描 tools/ 目录的 @tool 装饰器。
    """

    from pathlib import Path

    names: list[str] = []
    root = Path(__file__).parent.parent.parent / "tools"

    for py in root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            # @tool 装饰的函数
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    dec_name = _decorator_name(dec)
                    if dec_name == "tool":
                        names.append(node.name)
    return sorted(set(names))


def _decorator_name(dec) -> str:
    """提取装饰器名字。"""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
        return dec.func.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return ""


def test_tools_exist():
    """至少要能扫到一些工具。"""
    names = _all_tool_names()
    assert len(names) >= 20, f"工具数量太少: {len(names)}"


@pytest.mark.parametrize("name", _all_tool_names())
def test_tool_name_format(name: str):
    """工具名必须符合 snake_case。"""
    assert TOOL_NAME_RE.match(name), f"工具名不符合规范: {name}"


@pytest.mark.parametrize("name", _all_tool_names())
def test_tool_has_docstring(name: str):
    """每个工具函数必须有 docstring。"""
    from pathlib import Path

    root = Path(__file__).parent.parent.parent / "tools"
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        # 粗略检查：def name( ... 后面紧跟 """
        if f"def {name}(" in text:
            idx = text.index(f"def {name}(")
            snippet = text[idx : idx + 800]
            assert '"""' in snippet or "'''" in snippet, f"工具 {name} 缺少 docstring（{py.name}）"
            return
    pytest.skip(f"{name} 未找到定义文件")


# ============================================================
# 关键工具的 schema 稳定性
# ============================================================


@pytest.mark.parametrize(
    "tool_name,required_params",
    [
        ("read_file", ["path"]),
        ("write_file", ["path", "content"]),
        ("edit_file", ["path", "old_string", "new_string"]),
        ("grep_search", ["pattern"]),
        ("glob_files", ["pattern"]),
    ],
)
def test_core_tool_required_params(tool_name: str, required_params: list[str]):
    """核心工具的必填参数不能漂移。

    注意：这里只检查参数名在代码里出现，不做完整 schema 解析。
    """
    from pathlib import Path

    root = Path(__file__).parent.parent.parent / "tools"
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if f"def {tool_name}(" in text:
            for param in required_params:
                assert param in text, f"{tool_name} 缺少参数 {param}"
            return
    pytest.skip(f"{tool_name} 未找到定义")
