"""日志配置。

分层策略：
- 屏幕 handler: WARNING+（默认），AGENT_VERBOSE_LOGS=1 时降到 INFO+
- 文件 handler: INFO+，轮转写到 ~/.coding-agent/logs/coding-agent.log
- structlog: 结构化日志，两个 handler 走 ProcessorFormatter

第三方库（httpx / mcp / openai / docker / chromadb / ...）默认静音到 WARNING。

使用方式（调用方无需改动）：

    from observability.logger import configure_logging, get_logger, bind_context

    configure_logging(level="INFO", json_output=False)
    log = get_logger("core")
    bind_context(session_id="...", thread_id="...", trace_id="...")

    log.info("agent_build_start", provider="qwen", model="qwen-max")
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
import structlog.contextvars

# ============================================================
# 常量
# ============================================================

_LOG_DIR = Path.home() / ".coding-agent" / "logs"
_LOG_FILE = _LOG_DIR / "coding-agent.log"

# 静音的第三方库前缀
_NOISY_PREFIXES = (
    "httpx",
    "httpcore",
    "mcp",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_core",
    "openai",
    "anthropic",
    "urllib3",
    "filelock",
    "asyncio",
    "matplotlib",
    "chromadb",
    "sentence_transformers",
    "huggingface_hub",
    "transformers",
    "docker",
    "git",
)

# 共享的 structlog 处理器链（structlog 与 stdlib 日志都过一遍）
_SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]

_configured = False


# ============================================================
# 内部工具
# ============================================================


def _is_verbose() -> bool:
    """是否开启屏幕详细日志。"""
    return os.getenv("AGENT_VERBOSE_LOGS", "false").lower() in ("1", "true", "yes")


def _silence_noisy_loggers() -> None:
    """把第三方库日志压到 WARNING（除非 AGENT_VERBOSE_LOGS=1）。"""
    if _is_verbose():
        return

    # 1. 遍历已注册的所有 logger
    for name in list(logging.root.manager.loggerDict.keys()):
        if any(name == p or name.startswith(p + ".") for p in _NOISY_PREFIXES):
            logging.getLogger(name).setLevel(logging.WARNING)

    # 2. 兜底：按前缀直接设置，防止后续动态创建
    for p in _NOISY_PREFIXES:
        logging.getLogger(p).setLevel(logging.WARNING)


def _build_screen_formatter() -> structlog.stdlib.ProcessorFormatter:
    """屏幕输出的 formatter（彩色 ConsoleRenderer）。"""
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ],
    )


def _build_file_formatter(json_output: bool) -> structlog.stdlib.ProcessorFormatter:
    """文件输出的 formatter（无彩色 / JSON）。"""
    if json_output:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=False,
            exception_formatter=structlog.dev.plain_traceback,
        )

    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )


# ============================================================
# 对外 API
# ============================================================


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """配置日志。

    Args:
        level: 文件 handler 的最低级别，默认 "INFO"。
        json_output: 文件 handler 是否输出 JSON（生产环境推荐 True）。
    """
    global _configured
    if _configured:
        return
    _configured = True

    # ---------- 1. structlog 全局配置 ----------
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ---------- 2. stdlib root logger ----------
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # 清空已有的 handler，避免重复
    for h in list(root.handlers):
        root.removeHandler(h)

    # ---------- 3. 屏幕 handler（默认 WARNING+） ----------
    verbose = _is_verbose()
    screen_handler = logging.StreamHandler(sys.stderr)
    screen_handler.setLevel(logging.INFO if verbose else logging.WARNING)
    screen_handler.setFormatter(_build_screen_formatter())
    root.addHandler(screen_handler)

    # ---------- 4. 文件 handler（INFO+，轮转） ----------
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.setFormatter(_build_file_formatter(json_output))
    root.addHandler(file_handler)

    # ---------- 5. 静音第三方库 ----------
    _silence_noisy_loggers()


def get_logger(name: str = "coding-agent"):
    """获取 structlog logger。

    Args:
        name: logger 名（用于分类日志，如 "core" / "main" / "mcp"）。

    Returns:
        structlog BoundLogger，支持 `log.info("event", key=value)`。
    """
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def bind_context(**kwargs) -> None:
    """绑定上下文（session_id / thread_id / trace_id 等）。

    之后所有日志都会自动带上这些字段。

    Example:
        bind_context(session_id="proj", thread_id="abc", trace_id="xyz")
        log.info("task_started")   # 输出会带 session_id / thread_id / trace_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """解绑指定的上下文字段。"""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """清空所有上下文。"""
    structlog.contextvars.clear_contextvars()


def log_file_path() -> Path:
    """日志文件路径（供 CLI 提示用户）。"""
    return _LOG_FILE
