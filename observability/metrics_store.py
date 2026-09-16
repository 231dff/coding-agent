"""指标持久化存储（SQLite）。

替代原来的内存 _ring 缓冲区。
支持跨进程重启保留历史数据。

表结构：
    metrics(id, timestamp, kind, model, tool_name,
            input_tokens, output_tokens, cache_read_tokens,
            duration_ms, cost_usd, success)

性能优化：
- WAL 模式：读写并发不互相阻塞
- synchronous=NORMAL：写入更快，断电丢最后几条可接受
- temp_store=MEMORY：聚合查询的临时表放内存
- stats() 缓存 db_size，避免每次 stat 系统调用
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
            timeout=30.0,
            isolation_level=None,  # 自己控制事务
        )
        self._lock = threading.RLock()

        # ---- 性能 pragma ----
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")
        except sqlite3.DatabaseError:
            # 某些只读文件系统会拒绝 WAL，降级为默认模式
            pass

        # ---- 写入缓冲（batch commit） ----
        self._pending: list[tuple] = []
        self._pending_lock = threading.Lock()
        self._last_commit: float = time.time()
        self._commit_interval: float = 0.5  # 秒
        self._commit_batch_size: int = 50

        # ---- stats 缓存 ----
        self._stats_cache: dict | None = None
        self._stats_cache_at: float = 0.0
        self._stats_cache_ttl: float = 5.0  # 秒

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
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON metrics(timestamp)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_kind ON metrics(kind)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_kind_ts ON metrics(kind, timestamp)")

    # ---------- 写入缓冲 ----------

    def _enqueue(self, row: tuple) -> None:
        """把一条 INSERT 放进缓冲，达到阈值或超时后批量提交。"""
        should_flush = False
        with self._pending_lock:
            self._pending.append(row)
            now = time.time()
            if (
                len(self._pending) >= self._commit_batch_size
                or now - self._last_commit >= self._commit_interval
            ):
                should_flush = True
                batch = self._pending
                self._pending = []
                self._last_commit = now

        if should_flush:
            self._flush(batch)

    def _flush(self, batch: list[tuple]) -> None:
        if not batch:
            return
        try:
            with self._lock:
                self._conn.executemany(
                    "INSERT INTO metrics ("
                    "timestamp, kind, model, tool_name, "
                    "input_tokens, output_tokens, "
                    "cache_read_tokens, cache_write_tokens, "
                    "duration_ms, cost_usd, success"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
            self._invalidate_stats_cache()
        except Exception:
            # 写入失败不阻塞主流程
            pass

    def flush(self) -> None:
        """强制提交缓冲。"""
        with self._pending_lock:
            batch = self._pending
            self._pending = []
            self._last_commit = time.time()
        self._flush(batch)

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
        self._enqueue(
            (
                time.time(),
                "llm",
                model,
                None,
                int(input_tokens or 0),
                int(output_tokens or 0),
                int(cache_read_tokens or 0),
                int(cache_write_tokens or 0),
                float(duration_ms or 0.0),
                float(cost_usd or 0.0),
                1,
            )
        )

    def record_tool(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """记录一次工具调用。"""
        self._enqueue(
            (
                time.time(),
                "tool",
                None,
                tool_name,
                0,
                0,
                0,
                0,
                float(duration_ms or 0.0),
                0.0,
                1 if success else 0,
            )
        )

    def record_compaction(self, layer: str) -> None:
        """记录一次压缩事件（L1-L5）。"""
        self._enqueue(
            (
                time.time(),
                "compaction",
                None,
                layer,
                0,
                0,
                0,
                0,
                0.0,
                0.0,
                1,
            )
        )

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
        # 先把缓冲刷掉，保证查询能看到最新数据
        self.flush()

        now = time.time()
        start = now - range_seconds

        with self._lock:
            rows = self._conn.execute(
                """
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
            """,
                (bucket_seconds, bucket_seconds, start),
            ).fetchall()

            tool_rows = self._conn.execute(
                """
                SELECT tool_name, COUNT(*) AS cnt
                FROM metrics
                WHERE kind = 'tool' AND timestamp >= ?
                GROUP BY tool_name
            """,
                (start,),
            ).fetchall()

            compact_rows = self._conn.execute(
                """
                SELECT tool_name, COUNT(*) AS cnt
                FROM metrics
                WHERE kind = 'compaction' AND timestamp >= ?
                GROUP BY tool_name
            """,
                (start,),
            ).fetchall()

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
        self.flush()
        cutoff = time.time() - days * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._invalidate_stats_cache()
        return cur.rowcount

    def checkpoint(self) -> None:
        """把 WAL 合并回主库文件。"""
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.DatabaseError:
                pass

    # ---------- 统计 ----------

    def _invalidate_stats_cache(self) -> None:
        self._stats_cache = None
        self._stats_cache_at = 0.0

    def stats(self) -> dict:
        """存储统计。带 5 秒 TTL 缓存，避免频繁 stat。"""
        now = time.time()
        if self._stats_cache is not None and now - self._stats_cache_at < self._stats_cache_ttl:
            return self._stats_cache

        self.flush()

        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
            earliest = self._conn.execute("SELECT MIN(timestamp) FROM metrics").fetchone()[0]
            latest = self._conn.execute("SELECT MAX(timestamp) FROM metrics").fetchone()[0]

        size = 0
        try:
            if self.path.exists():
                size = self.path.stat().st_size
        except OSError:
            pass

        result = {
            "total_rows": total,
            "earliest": earliest,
            "latest": latest,
            "db_path": str(self.path),
            "db_size_bytes": size,
        }
        self._stats_cache = result
        self._stats_cache_at = now
        return result

    # ---------- 关闭 ----------

    def close(self) -> None:
        try:
            self.flush()
        except Exception:
            pass
        try:
            self.checkpoint()
        except Exception:
            pass
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> MetricsStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()
