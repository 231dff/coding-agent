"""Day 24: 测试工具的 LangChain 封装。"""
from __future__ import annotations

from langchain.tools import tool

from sandbox.base import Sandbox
from agent.test_loop import parse_test_output


_SANDBOX: Sandbox | None = None


def bind(sandbox: Sandbox) -> None:
    global _SANDBOX
    _SANDBOX = sandbox


@tool
def run_tests(command: str = "pytest tests/ -v --tb=short") -> str:
    """在沙箱内运行测试，返回结构化结果。

    这是验证修改是否正确的主要方式。
    完成代码修改后 ALWAYS 运行测试。

    Args:
        command: 测试命令，默认 pytest。
    """
    if _SANDBOX is None:
        return "ERROR: 沙箱未初始化"

    result = _SANDBOX.exec(command, timeout=120)
    output = result.stdout + result.stderr

    parsed = parse_test_output(output)
    summary = (
        f"测试结果: {'✓ 全部通过' if parsed.passed else '✗ 存在失败'}\n"
        f"总数: {parsed.total}, 失败: {parsed.failed}\n"
    )
    if parsed.errors:
        summary += "失败用例:\n" + "\n".join(f"  - {e}" for e in parsed.errors[:10])

    # 截断输出
    if len(output) > 3000:
        output = output[:3000] + f"\n... (truncated, {len(output)} chars total)"

    return summary + "\n\n完整输出:\n" + output


@tool
def parse_error(output: str) -> str:
    """解析错误输出，提取关键信息。

    Args:
        output: 原始错误输出。
    """
    lines = output.splitlines()
    key_lines = []

    for line in lines:
        # 提取异常类型
        if re.match(r"^\w+Error:", line) or re.match(r"^\w+Exception:", line):
            key_lines.append(f"异常: {line}")
        # 提取文件位置
        elif re.match(r'^\s+File "', line):
            key_lines.append(f"位置: {line.strip()}")
        # 提取断言失败
        elif "AssertionError" in line:
            key_lines.append(f"断言: {line.strip()}")

    if not key_lines:
        return "未能提取到关键错误信息，请检查完整输出。"

    return "\n".join(key_lines[:20])


import re

TEST_TOOLS = ["run_tests", "parse_error"]