"""Day 26: LangGraph Store 封装。

区分两种记忆：
- Checkpointer (短期): 以 thread 为单位保存对话状态，每步 checkpoint
- Store (长期): 跨 thread、跨 session 存储用户或应用级数据

生产环境用 Postgres，开发用 SQLite。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.store.base import BaseStore


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
        from langgraph.store.sqlite import SqliteStore

        path = conn_string or ".agent_memory/store.db"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return SqliteStore(conn_string=f"file:{path}")

    if backend == "postgres":
        from langgraph.store.postgres import PostgresStore

        dsn = conn_string or os.getenv("POSTGRES_DSN")
        if not dsn:
            raise ValueError("Postgres 需要 POSTGRES_DSN 或 conn_string")
        # 使用连接池
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
