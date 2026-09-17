"""会话 checkpointer。

用 SQLite 持久化 LangGraph 的会话状态，支持跨进程恢复。

存储位置：<project>/.coding-agent/sessions/checkpoints.db
每行记录一次 graph 节点执行后的完整 state（含所有 messages、tool_calls）。

设计：
- 一个项目一个 DB 文件，进程内多会话共享
- thread_id 即会话 ID（CLI 默认按项目路径生成）
- WAL 模式 + 30s 超时，兼容多进程访问
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def build_checkpointer(meta_dir: Path) -> SqliteSaver:
    """构造 SQLite checkpointer。

    Args:
        meta_dir: Agent 元数据目录（通常是 <project>/.coding-agent/）。

    Returns:
        SqliteSaver 实例，可直接传给 create_agent。
    """
    db_path = meta_dir / "sessions" / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
        timeout=30.0,
    )
    # WAL 模式：读写不互斥，兼容多进程
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass

    return SqliteSaver(conn)


def list_threads(meta_dir: Path) -> list[dict]:
    """列出所有历史会话。

    Returns:
        [{thread_id, checkpoints, last_update}, ...]，按最近活跃排序。
    """
    db_path = meta_dir / "sessions" / "checkpoints.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        rows = conn.execute("""
            SELECT thread_id, COUNT(*) AS n, MAX(created_at) AS last
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY last DESC
        """).fetchall()
        return [
            {
                "thread_id": r[0],
                "checkpoints": r[1],
                "last_update": r[2],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        # 表还没建（第一次运行）
        return []
    finally:
        conn.close()


def delete_thread(meta_dir: Path, thread_id: str) -> int:
    """删除一个会话的所有 checkpoints。返回删除的记录数。"""
    db_path = meta_dir / "sessions" / "checkpoints.db"
    if not db_path.exists():
        return 0

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        cur = conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.commit()
        return cur.rowcount
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()
