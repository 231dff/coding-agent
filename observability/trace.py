"""全链路 trace_id 生成与传播。

用途：
- 一次用户会话/请求对应一个 trace_id
- 所有日志、工具调用、LLM 调用自动带 trace_id
- 便于生产环境定位问题

用法：
    from observability.trace import new_trace_id, get_trace_id

    # 会话开始时
    tid = new_trace_id()

    # 任意位置读取
    from observability.logger import get_logger
    log = get_logger("core")
    log.info("event")  # 自动带 trace_id
"""

from __future__ import annotations

import contextvars
import uuid

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def new_trace_id() -> str:
    """生成一个新的 trace_id 并设为当前。

    Returns:
        12 位十六进制字符串。
    """
    tid = uuid.uuid4().hex[:12]
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str:
    """读取当前 trace_id。未设置时返回空字符串。"""
    return _trace_id.get() or ""


def set_trace_id(tid: str) -> None:
    """显式设置 trace_id（用于从上游透传）。"""
    _trace_id.set(tid)


def reset_trace_id() -> None:
    """清空当前 trace_id。"""
    _trace_id.set("")
