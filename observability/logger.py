"""结构化日志。

JSON lines 格式，便于日志聚合系统解析。
也提供人类可读模式（开发环境）。
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

import structlog


# 请求级上下文
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")
_thread_id: ContextVar[str] = ContextVar("thread_id", default="")


def bind_context(
    request_id: str = "",
    session_id: str = "",
    thread_id: str = "",
) -> None:
    """绑定请求上下文。在每轮对话开始时调用。"""
    if request_id:
        _request_id.set(request_id)
    if session_id:
        _session_id.set(session_id)
    if thread_id:
        _thread_id.set(thread_id)


def _add_timestamp(logger, method_name, event_dict):
    """structlog processor：添加时间戳。"""
    event_dict["timestamp"] = time.time()
    return event_dict


def _add_context(logger, method_name, event_dict):
    """structlog processor：添加上下文信息。"""
    if _request_id.get():
        event_dict["request_id"] = _request_id.get()
    if _session_id.get():
        event_dict["session_id"] = _session_id.get()
    if _thread_id.get():
        event_dict["thread_id"] = _thread_id.get()
    return event_dict


def _render_json(logger, method_name, event_dict):
    """structlog processor：JSON 序列化。"""
    return json.dumps(event_dict, ensure_ascii=False, default=str)


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """配置日志。

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）。
        json_output: True 输出 JSON lines；False 输出人类可读格式。
    """
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_timestamp,
        _add_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(_render_json)
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "coding-agent"):
    """获取 logger。"""
    return structlog.get_logger(name)


# ============================================================
# 便捷日志函数
# ============================================================

def log_llm_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_s: float,
    cost_usd: float = 0.0,
) -> None:
    get_logger("llm").info(
        "llm_call",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_s=round(duration_s, 3),
        cost_usd=round(cost_usd, 6),
    )


def log_tool_call(
    tool_name: str,
    duration_s: float,
    success: bool,
    error: str = "",
) -> None:
    get_logger("tool").info(
        "tool_call",
        tool=tool_name,
        duration_s=round(duration_s, 3),
        success=success,
        error=error[:200] if error else "",
    )


def log_compaction(layer: str, before_tokens: int, after_tokens: int) -> None:
    get_logger("compaction").info(
        "compaction",
        layer=layer,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        saved_tokens=before_tokens - after_tokens,
    )


def log_error(error: Exception, context: dict[str, Any] | None = None) -> None:
    get_logger("error").error(
        "exception",
        error_type=type(error).__name__,
        error_message=str(error),
        context=context or {},
    )