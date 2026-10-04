"""P4: 从三个数据源聚合统计快照。

数据源：
  1. <meta_dir>/evolution/experiences.jsonl   — 任务判定、审查结果
  2. <meta_dir>/trajectories/session-*.jsonl   — 工具调用
  3. ~/.coding-agent/metrics.db                — token 成本

容错原则：任何一个源不可用都不阻断，返回已收集的部分。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .schema import StatsSnapshot, TaskStats


def collect(
    meta_dir: Path | str,
    metrics_db: Path | str | None = None,
    days: int = 7,
) -> StatsSnapshot:
    """
    Args:
        meta_dir: 项目级元数据目录（如 D:/proj/.coding-agent）
        metrics_db: 全局 metrics.db 路径（默认 ~/.coding-agent/metrics.db）
        days: 时间窗口
    """
    meta_dir = Path(meta_dir)
    snap = StatsSnapshot()

    # ---------- 1. experiences.jsonl ----------
    experiences = _load_experiences(meta_dir / "evolution" / "experiences.jsonl")
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    recent = [e for e in experiences if e.get("ts", 0) >= cutoff]

    for e in recent:
        success = bool(e.get("success"))
        verdict = e.get("verdict", "uncertain")
        snap.tasks.append(
            TaskStats(
                session_id=e.get("session_id", "?"),
                ts=float(e.get("ts", 0)),
                task=e.get("task", "")[:100],
                verdict=verdict,
                success=success,
                tool_calls=int(e.get("tool_calls_count", 0)),
                files_changed=len(e.get("files_changed", [])),
                reviewer_verdict=e.get("reviewer_verdict", ""),
                reviewer_confidence=float(e.get("reviewer_confidence", 0.0)),
                failed_dimensions=e.get("failed_dimensions", []),
            )
        )

        if verdict == "pass":
            snap.success_count += 1
        elif verdict == "fail":
            snap.fail_count += 1
        else:
            snap.uncertain_count += 1

        if e.get("veto_triggered"):
            snap.veto_count += 1

        for d in e.get("failed_dimensions", []):
            snap.failed_dimensions[d] = snap.failed_dimensions.get(d, 0) + 1
        for d in e.get("uncertain_dimensions", []):
            snap.uncertain_dimensions[d] = snap.uncertain_dimensions.get(d, 0) + 1
        rv = e.get("reviewer_verdict", "")
        if rv:
            snap.reviewer_distribution[rv] = snap.reviewer_distribution.get(rv, 0) + 1

    snap.total_tasks = len(snap.tasks)

    # ---------- 2. trajectories/*.jsonl（工具使用） ----------
    snap.tool_usage = _collect_tool_usage(meta_dir / "trajectories", cutoff)

    # ---------- 3. metrics.db（成本） ----------
    if metrics_db is None:
        metrics_db = Path.home() / ".coding-agent" / "metrics.db"
    snap.total_cost_usd, snap.cost_by_model = _collect_cost(Path(metrics_db), cutoff)

    # ---------- 4. 时间序列 ----------
    snap.daily = _build_daily(snap.tasks, days)

    # ---------- 5. 健康度 ----------
    if snap.tasks:
        snap.avg_tool_calls = sum(t.tool_calls for t in snap.tasks) / len(snap.tasks)

    return snap


# ---------- 内部 ----------


def _load_experiences(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _collect_tool_usage(traj_dir: Path, cutoff: float) -> dict[str, int]:
    if not traj_dir.exists():
        return {}
    counter: Counter = Counter()
    for f in traj_dir.glob("session-*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = rec.get("event") or rec.get("type")
            if etype != "tool_call":
                continue
            name = rec.get("name") or (rec.get("data") or {}).get("name")
            if name:
                counter[name] += 1
    return dict(counter)


def _collect_cost(db_path: Path, cutoff: float) -> tuple[float, dict[str, float]]:
    """
    metrics.db 的 schema 由项目定义。尝试常见的字段名：
      ts / timestamp, cost / cost_usd / total_cost, model / model_name
    失败时返回 (0.0, {})。
    """
    if not db_path.exists():
        return 0.0, {}
    try:
        import sqlite3
    except ImportError:
        return 0.0, {}

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 20")
        tables = [r[0] for r in cur.fetchall()]
        if not tables:
            return 0.0, {}

        total = 0.0
        by_model: dict[str, float] = {}

        for table in tables:
            cols = _get_columns(conn, table)
            ts_col = _pick(cols, ["ts", "timestamp", "created_at", "time"])
            cost_col = _pick(cols, ["cost_usd", "cost", "total_cost", "price"])
            model_col = _pick(cols, ["model_name", "model", "provider"])
            if not cost_col:
                continue

            # ★ 修复：用局部变量代替 f-string 内嵌引号表达式
            if model_col:
                select_cols = f"{cost_col}, {model_col}"
            else:
                select_cols = f"{cost_col}, '' AS __model"

            if ts_col:
                sql = f"SELECT {select_cols} FROM {table} WHERE {ts_col} >= ?"
                params: tuple = (cutoff,)
            else:
                sql = f"SELECT {select_cols} FROM {table}"
                params = ()

            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                continue

            for r in rows:
                c = float(r[0] or 0)
                total += c
                m = str(r[1] or "unknown") if len(r) > 1 else "unknown"
                by_model[m] = by_model.get(m, 0.0) + c

        conn.close()
        return total, by_model
    except Exception:
        return 0.0, {}


def _get_columns(conn, table: str) -> list[str]:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    except Exception:
        return []


def _pick(candidates: list[str], wanted: list[str]) -> str | None:
    for w in wanted:
        if w in candidates:
            return w
    return None


def _build_daily(tasks: list[TaskStats], days: int) -> list[tuple[str, int, int]]:
    """返回 [(YYYY-MM-DD, total, success), ...]，从今天往前 days 天。"""
    buckets: dict[str, list[int]] = {}
    today = datetime.now().date()
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        buckets[d] = [0, 0]

    for t in tasks:
        try:
            d = datetime.fromtimestamp(t.ts).date().isoformat()
        except (ValueError, OSError):
            continue
        if d in buckets:
            buckets[d][0] += 1
            if t.success:
                buckets[d][1] += 1

    return [(d, v[0], v[1]) for d, v in sorted(buckets.items())]
