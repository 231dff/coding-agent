"""结构化日志。

处理器链：
1. 注入 trace_id
2. 脱敏（key / password / token / DSN 密码）
3. 时间戳
4. 日志级别
5. 渲染（dev: 彩色，prod: JSON）

用法：
    from observability.logger import (
        configure_logging, get_logger, bind_context,
    )

    configure_logging(level="INFO", json_output=False)
    log = get_logger("core")
    log.info("event", key="value")
"""

from __future__ import annotations

import logging

import structlog

from observability.redact import redact_deep
from observability.trace import get_trace_id

# ============================================================
# 自定义 processor
# ============================================================


def _add_trace_id(logger, method_name, event_dict):
    """注入当前 trace_id。"""
    tid = get_trace_id()
    if tid:
        event_dict["trace_id"] = tid
    return event_dict


def _redact_processor(logger, method_name, event_dict):
    """脱敏（key / token / password / DSN 密码）。"""
    return redact_deep(event_dict)


# ============================================================
# 配置
# ============================================================


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """配置 structlog。

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）
        json_output: True 输出 JSON，False 输出彩色文本
    """
    shared_processors = [
        # contextvars 里的上下文（bind_context 绑定）
        structlog.contextvars.merge_contextvars,
        # 日志级别
        structlog.processors.add_log_level,
        # 注入 trace_id
        _add_trace_id,
        # 脱敏
        _redact_processor,
        # 时间戳
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer(
            ensure_ascii=False,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )

    # Python 标准 logging 也重定向到 structlog
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app"):
    """获取带 name 的 logger。"""
    return structlog.get_logger(name)


def bind_context(**kwargs) -> None:
    """绑定上下文到所有后续日志（同一 async task / 线程内有效）。

    典型用法：
        bind_context(session_id="sess-xxx", thread_id="abc")
        log.info("event")  # 自动带 session_id 和 thread_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """解绑指定 key 的上下文。"""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """清空所有绑定的上下文。"""
    structlog.contextvars.clear_contextvars()
