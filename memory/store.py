"""LangGraph Store 封装 + 记忆系统全局工厂。

区分两种记忆：
- Checkpointer (短期): 以 thread 为单位保存对话状态，每步 checkpoint
- Store (长期): 跨 thread、跨 session 存储用户或应用级数据

生产环境用 Postgres，开发用 SQLite。

修复记录：
  - 2026-10-06 v1：多线程同时 BEGIN → "cannot start a transaction within a transaction"
    → 引入 LockedStore 串行化
  - 2026-10-06 v2：python sqlite3 默认隐式事务 + LangGraph 显式 BEGIN 冲突
    → 连接时设 isolation_level=None，让 LangGraph 完全接管事务
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.store.base import BaseStore

# ============================================================
# 原有 API（保持不变）
# ============================================================


def create_store(
    backend: str = "sqlite",
    conn_string: str | None = None,
) -> BaseStore:
    """创建 Store 实例。

    Args:
        backend: "sqlite" | "postgres" | "memory"
        conn_string: 连接字符串。sqlite 为文件路径，postgres 为 DSN。
    """
    if backend == "memory":
        from langgraph.store.memory import InMemoryStore

        return InMemoryStore()

    if backend == "sqlite":
        import sqlite3

        from langgraph.store.sqlite import SqliteStore

        path = conn_string or ".agent_memory/store.db"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # ★ isolation_level=None：autocommit 模式
        #   让 LangGraph 完全接管 BEGIN/COMMIT/ROLLBACK
        conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,
        )
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.DatabaseError:
            pass

        return SqliteStore(conn)

    if backend == "postgres":
        from langgraph.store.postgres import PostgresStore

        dsn = conn_string or os.getenv("POSTGRES_DSN")
        if not dsn:
            raise ValueError("Postgres 需要 POSTGRES_DSN 或 conn_string")
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(dsn, min_size=1, max_size=10)
        return PostgresStore(pool)

    raise ValueError(f"未知 backend: {backend}")


@contextmanager
def store_context(
    backend: str = "sqlite",
    conn_string: str | None = None,
) -> Iterator[BaseStore]:
    """上下文管理器，确保 store 正确关闭。"""
    store = create_store(backend, conn_string)
    try:
        yield store
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()


# ============================================================
# LockedStore：给 Store 加全局锁
# ============================================================


class LockedStore:
    """给 Store 加全局锁，串行化所有操作。

    解决多线程环境下 SqliteStore 事务冲突。

    不继承 BaseStore——避免抽象方法问题；运行时只按鸭子类型使用。
    """

    def __init__(self, inner: BaseStore):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_lock", threading.RLock())

    def put(self, *args, **kwargs):
        with self._lock:
            return self._inner.put(*args, **kwargs)

    def get(self, *args, **kwargs):
        with self._lock:
            return self._inner.get(*args, **kwargs)

    def search(self, *args, **kwargs):
        with self._lock:
            return self._inner.search(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with self._lock:
            return self._inner.delete(*args, **kwargs)

    def batch(self, *args, **kwargs):
        with self._lock:
            return self._inner.batch(*args, **kwargs)

    def list_namespaces(self, *args, **kwargs):
        with self._lock:
            return self._inner.list_namespaces(*args, **kwargs)

    def __getattr__(self, name):
        # 兜底：其他方法直接转发 + 加锁
        attr = getattr(self._inner, name)
        if callable(attr):

            def _wrapped(*args, **kwargs):
                with self._lock:
                    return attr(*args, **kwargs)

            return _wrapped
        return attr


# ============================================================
# 全局单例 + 环境变量工厂
# ============================================================

_STORE: LockedStore | None = None
_STORE_LOCK = threading.Lock()


def agent_home() -> Path:
    """全局 Agent 目录。"""
    env = os.getenv("AGENT_HOME", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".coding-agent"


def get_store() -> LockedStore:
    """返回全局 Store 单例（已加锁）。

    环境变量：
    - AGENT_STORE_BACKEND: "sqlite" / "postgres" / "memory"（默认 sqlite）
    - AGENT_STORE_DSN: sqlite 时为文件路径，postgres 时为 DSN
    - POSTGRES_DSN: 兼容标准名
    """
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE

        backend = os.getenv("AGENT_STORE_BACKEND", "sqlite").lower()

        if backend == "sqlite":
            default_path = agent_home() / "memory" / "store.db"
            conn = os.getenv("AGENT_STORE_DSN", str(default_path))
            _STORE = LockedStore(create_store("sqlite", conn))

        elif backend == "postgres":
            dsn = os.getenv("AGENT_STORE_DSN", "") or os.getenv("POSTGRES_DSN", "")
            if not dsn:
                default_path = agent_home() / "memory" / "store.db"
                _STORE = LockedStore(create_store("sqlite", str(default_path)))
            else:
                try:
                    _STORE = LockedStore(create_store("postgres", dsn))
                except Exception:
                    default_path = agent_home() / "memory" / "store.db"
                    _STORE = LockedStore(create_store("sqlite", str(default_path)))

        elif backend == "memory":
            _STORE = LockedStore(create_store("memory"))

        else:
            raise ValueError(f"未知 AGENT_STORE_BACKEND: {backend}")

        return _STORE


def reset_store() -> None:
    """重置单例（测试用）。"""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            close = getattr(_STORE._inner, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        _STORE = None


def current_user_id() -> str:
    """当前用户 ID。"""
    return os.getenv("AGENT_USER_ID", "default")


def store_backend_info() -> dict:
    """返回当前 store 后端信息（调试用）。"""
    backend = os.getenv("AGENT_STORE_BACKEND", "sqlite").lower()
    info = {"backend": backend}

    try:
        store = get_store()
        info["type"] = type(store).__name__
    except Exception as e:
        info["error"] = str(e)

    return info
