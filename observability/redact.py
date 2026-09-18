"""日志脱敏。

对敏感字段做掩码处理：
- key / token / password / secret / credential 相关字段 → ***
- DSN 里的密码部分 → ***

用法：
    from observability.redact import redact_dict

    safe = redact_dict({"api_key": "sk-abc", "model": "gpt-4"})
    # → {"api_key": "***", "model": "gpt-4"}
"""

from __future__ import annotations

import re
from typing import Any

# 敏感字段名（不区分大小写）
# 覆盖常见 token 变体：access / auth / refresh / bearer / id / session
SENSITIVE_KEY_RE = re.compile(
    r"("
    r"api[_-]?key|"
    r"access[_-]?token|"
    r"auth[_-]?token|"
    r"refresh[_-]?token|"
    r"bearer[_-]?token|"
    r"id[_-]?token|"
    r"session[_-]?token|"
    r"password|"
    r"secret|"
    r"credential|"
    r"private[_-]?key"
    r")",
    re.IGNORECASE,
)

# DSN 里的密码：protocol://user:pass@host → protocol://user:***@host
DSN_PASSWORD_RE = re.compile(r"://([^:/\s]+):([^@\s]+)@")


def redact_value(key: str, value: Any) -> Any:
    """对单个值脱敏。"""
    if SENSITIVE_KEY_RE.search(key):
        return "***"

    if isinstance(value, str):
        # DSN 里的密码
        return DSN_PASSWORD_RE.sub(r"://\1:***@", value)

    return value


def redact_dict(data: dict) -> dict:
    """对字典脱敏（浅层）。"""
    if not isinstance(data, dict):
        return data
    return {k: redact_value(k, v) for k, v in data.items()}


def redact_deep(data: Any, _depth: int = 0) -> Any:
    """递归脱敏（有深度限制）。"""
    if _depth > 5:
        return data

    if isinstance(data, dict):
        return {k: redact_deep(redact_value(k, v), _depth + 1) for k, v in data.items()}

    if isinstance(data, list):
        # 只处理前 50 项，避免大列表卡住
        return [redact_deep(item, _depth + 1) for item in data[:50]]

    return data
