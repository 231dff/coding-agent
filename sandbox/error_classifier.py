"""错误分类器。

书中 5.1.7：先分类，再计数。
可重试的错误（限流、网络抖动）重试才有意义；
不可重试的错误（参数不合法、权限不足）原样重试都是同样结果。
"""
from __future__ import annotations

import re
from enum import Enum


class ErrorClass(str, Enum):
    """错误类别。"""
    RETRYABLE = "retryable"           # 限流、超时、网络抖动
    INPUT_INVALID = "input_invalid"   # 参数不合法、依赖缺失
    PERMISSION = "permission"          # 权限不足
    NOT_FOUND = "not_found"            # 资源不存在
    DESTRUCTIVE = "destructive"        # 危险操作被拒
    UNKNOWN = "unknown"


# 匹配模式（按优先级顺序）
_PATTERNS: list[tuple[ErrorClass, list[str]]] = [
    (ErrorClass.RETRYABLE, [
        r"\b429\b",
        r"rate.?limit",
        r"too many requests",
        r"timeout",
        r"timed out",
        r"connection (reset|refused|aborted)",
        r"temporarily unavailable",
        r"service unavailable",
        r"\b503\b",
        r"\b502\b",
        r"\b504\b",
    ]),
    (ErrorClass.PERMISSION, [
        r"permission denied",
        r"access denied",
        r"\b403\b",
        r"not authorized",
        r"unauthorized",
        r"\b401\b",
        r"forbidden",
    ]),
    (ErrorClass.NOT_FOUND, [
        r"no such file",
        r"file not found",
        r"does not exist",
        r"\b404\b",
        r"unknown (command|module|tool)",
    ]),
    (ErrorClass.INPUT_INVALID, [
        r"no module named",
        r"command not found",
        r"invalid argument",
        r"invalid parameter",
        r"missing required",
        r"syntax error",
        r"jsondecodeerror",
        r"parse error",
        r"typeerror",
        r"valueerror",
    ]),
    (ErrorClass.DESTRUCTIVE, [
        r"destructive operation",
        r"rejected by policy",
        r"dangerous command",
    ]),
]


def classify_error(error_text: str) -> ErrorClass:
    """对错误信息分类。"""
    lower = error_text.lower()
    for error_class, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lower):
                return error_class
    return ErrorClass.UNKNOWN


def is_retryable(error_text: str) -> bool:
    """便捷函数：判断是否可重试。"""
    return classify_error(error_text) == ErrorClass.RETRYABLE


def suggest_recovery(error_text: str, tool_name: str) -> str:
    """根据错误类别和工具名生成恢复建议。"""
    error_class = classify_error(error_text)

    if error_class == ErrorClass.RETRYABLE:
        return f"错误可重试。建议：等待后重试或增加 timeout 参数。"
    if error_class == ErrorClass.INPUT_INVALID:
        if "no module named" in error_text.lower():
            return f"缺少依赖。建议：先调用 diagnose_sandbox 再 install_deps。"
        if "command not found" in error_text.lower():
            return f"命令不存在。建议：检查拼写或 install_deps。"
        return f"参数或输入不合法。建议：改变输入而非重试。"
    if error_class == ErrorClass.PERMISSION:
        return f"权限不足。建议：报告给用户，不要尝试绕过。"
    if error_class == ErrorClass.NOT_FOUND:
        return f"资源不存在。建议：用 glob_files 或 ls_dir 确认路径。"
    if error_class == ErrorClass.DESTRUCTIVE:
        return f"危险操作被拒。建议：换用更安全的替代方案。"
    return f"未分类错误。建议：分析完整错误信息后换策略，不要盲目重试。"