"""指标持久化存储（SQLite）。

替代原来的内存 _ring 缓冲区。
支持跨进程重启保留历史数据。

表结构：
    metrics(id, timestamp, kind, model, tool_name,
            input_tokens, output_tokens, cache_read_tokens,
            duration_ms, cost_usd, success)
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class MetricsStore:
    """SQLite 后端的指标存储。

    线程安全（内部加锁），支持多线程并发写入。
    """

    def __init__(self, db_path: str | Path = ".coding-agent/metrics.db"):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._lock = threading.Lock()
        self._init_schema()

    # ---------- 初始化 ----------

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    kind TEXT NOT NULL,
                    model TEXT,
                    tool_name TEXT,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cache_read_tokens INTEGER DEFAULT 0,
                    cache_write_tokens INTEGER DEFAULT 0,
                    duration_ms REAL DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    success INTEGER DEFAULT 1
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON metrics(timestamp)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kind ON metrics(kind)"
            )
            self._conn.commit()

    # ---------- 写入 ----------

    def record_llm(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        duration_ms: float = 0.0,
        cost_usd: float = 0.0,
    ) -> None:
        """记录一次 LLM 调用。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO metrics ("
                "timestamp, kind, model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, duration_ms, cost_usd"
                ") VALUES (?, 'llm', ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    model,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    duration_ms,
                    cost_usd,
                ),
            )
            self._conn.commit()

    def record_tool(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """记录一次工具调用。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO metrics ("
                "timestamp, kind, tool_name, duration_ms, success"
                ") VALUES (?, 'tool', ?, ?, ?)",
                (time.time(), tool_name, duration_ms, 1 if success else 0),
            )
            self._conn.commit()

    def record_compaction(self, layer: str) -> None:
        """记录一次压缩事件（L1-L5）。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO metrics ("
                "timestamp, kind, tool_name"
                ") VALUES (?, 'compaction', ?)",
                (time.time(), layer),
            )
            self._conn.commit()

    # ---------- 查询 ----------

    def query_timeseries(
        self,
        range_seconds: int,
        bucket_seconds: int,
    ) -> tuple[list[dict], dict, dict]:
        """按时间桶聚合。

        Returns:
            (points, tool_totals, compaction_totals)
        """
        now = time.time()
        start = now - range_seconds

        # 时序点
        with self._lock:
            rows = self._conn.execute("""
                SELECT
                    CAST(timestamp / ? AS INTEGER) * ? AS bucket,
                    SUM(CASE WHEN kind = 'llm' THEN 1 ELSE 0 END) AS llm_calls,
                    SUM(CASE WHEN kind = 'tool' THEN 1 ELSE 0 END) AS tool_calls,
                    SUM(CASE WHEN kind = 'llm' THEN input_tokens ELSE 0 END) AS input_tokens,
                    SUM(CASE WHEN kind = 'llm' THEN output_tokens ELSE 0 END) AS output_tokens,
                    SUM(CASE WHEN kind = 'llm' THEN cache_read_tokens ELSE 0 END) AS cache_read_tokens,
                    SUM(CASE WHEN kind = 'llm' THEN cache_write_tokens ELSE 0 END) AS cache_write_tokens,
                    SUM(cost_usd) AS cost_usd,
                    AVG(CASE WHEN duration_ms > 0 THEN duration_ms END) AS avg_latency_ms
                FROM metrics
                WHERE timestamp >= ?
                GROUP BY bucket
                ORDER BY bucket
            """, (bucket_seconds, bucket_seconds, start)).fetchall()

            # 工具计数
            tool_rows = self._conn.execute("""
                SELECT tool_name, COUNT(*) AS cnt
                FROM metrics
                WHERE kind = 'tool' AND timestamp >= ?
                GROUP BY tool_name
            """, (start,)).fetchall()

            # 压缩层计数
            compact_rows = self._conn.execute("""
                SELECT tool_name, COUNT(*) AS cnt
                FROM metrics
                WHERE kind = 'compaction' AND timestamp >= ?
                GROUP BY tool_name
            """, (start,)).fetchall()

        points = [
            {
                "timestamp": r[0],
                "llm_calls": r[1] or 0,
                "tool_calls": r[2] or 0,
                "input_tokens": r[3] or 0,
                "output_tokens": r[4] or 0,
                "cache_read_tokens": r[5] or 0,
                "cache_write_tokens": r[6] or 0,
                "cost_usd": round(r[7] or 0.0, 6),
                "avg_latency_ms": round(r[8] or 0.0, 1),
                "tool_breakdown": {},
                "compaction_layers": {},
            }
            for r in rows
        ]

        tool_totals = {r[0]: r[1] for r in tool_rows if r[0]}
        compaction_totals = {r[0]: r[1] for r in compact_rows if r[0]}

        return points, tool_totals, compaction_totals

    # ---------- 维护 ----------

    def prune_older_than(self, days: int = 30) -> int:
        """删除 N 天前的数据。返回删除的行数。"""
        cutoff = time.time() - days * 86400
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM metrics WHERE timestamp < ?", (cutoff,)
            )
            self._conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        """存储统计。"""
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM metrics"
            ).fetchone()[0]
            earliest = self._conn.execute(
                "SELECT MIN(timestamp) FROM metrics"
            ).fetchone()[0]
            latest = self._conn.execute(
                "SELECT MAX(timestamp) FROM metrics"
            ).fetchone()[0]

        return {
            "total_rows": total,
            "earliest": earliest,
            "latest": latest,
            "db_path": str(self.path),
            "db_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "MetricsStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()