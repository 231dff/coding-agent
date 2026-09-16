"""时序指标 API。

数据源：observability/metrics_store.MetricsStore（SQLite）。
mock 模式返回模拟数据；real 模式返回真实数据（无 mock 兜底）。
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from observability.metrics_store import MetricsStore

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

AGENT_MODE = os.getenv("AGENT_MODE", "mock").lower()


# ============================================================
# 数据模型
# ============================================================


class MetricPoint(BaseModel):
    timestamp: float
    llm_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    avg_latency_ms: float
    tool_breakdown: dict[str, int]
    compaction_layers: dict[str, int]


class SummaryStats(BaseModel):
    total_llm_calls: int
    total_tool_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    cache_hit_rate: float


class TimeseriesResponse(BaseModel):
    range: str
    bucket_seconds: int
    points: list[MetricPoint]
    summary: SummaryStats
    tool_totals: dict[str, int]
    compaction_totals: dict[str, int]


# ============================================================
# Store 单例
# ============================================================

_store: MetricsStore | None = None


def get_store() -> MetricsStore:
    global _store
    if _store is None:
        # 从环境变量或默认路径
        db_path = os.getenv(
            "AGENT_METRICS_DB",
            str(Path.home() / ".coding-agent" / "metrics.db"),
        )
        _store = MetricsStore(db_path)
    return _store


# ============================================================
# 时间范围配置
# ============================================================

_RANGE_CONFIG: dict[str, tuple[int, int]] = {
    "1h": (3600, 60),
    "24h": (86400, 900),
    "7d": (7 * 86400, 3600),
    "30d": (30 * 86400, 3 * 3600),
    "all": (30 * 86400, 3 * 3600),
}


# ============================================================
# Mock 数据生成
# ============================================================


def _generate_mock_series(
    range_seconds: int,
    bucket_seconds: int,
) -> list[MetricPoint]:
    now = time.time()
    start = now - range_seconds
    n_buckets = max(1, range_seconds // bucket_seconds)

    points: list[MetricPoint] = []
    base_load = 1.0

    for i in range(n_buckets):
        ts = start + i * bucket_seconds
        base_load = max(0.2, base_load * (0.9 + random.random() * 0.2))

        llm_calls = int(base_load * (3 + random.randint(0, 5))) or 1
        tool_calls = int(llm_calls * (1.2 + random.random() * 0.8))
        input_tokens = llm_calls * random.randint(800, 3200)
        output_tokens = llm_calls * random.randint(150, 900)
        cache_read = int(input_tokens * random.uniform(0.4, 0.8))
        cache_write = int(input_tokens * random.uniform(0.05, 0.15))

        cost = (
            input_tokens * 1.6 / 1e6
            + output_tokens * 6.4 / 1e6
            + cache_read * 0.16 / 1e6
            + cache_write * 2.0 / 1e6
        )

        points.append(
            MetricPoint(
                timestamp=ts,
                llm_calls=llm_calls,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=round(cost, 6),
                avg_latency_ms=round(random.uniform(800, 3500), 1),
                tool_breakdown={},
                compaction_layers={},
            )
        )

    return points


# ============================================================
# 汇总
# ============================================================


def _summarize(points: list[MetricPoint]) -> SummaryStats:
    if not points:
        return SummaryStats(
            total_llm_calls=0,
            total_tool_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_read_tokens=0,
            total_cost_usd=0.0,
            avg_latency_ms=0.0,
            cache_hit_rate=0.0,
        )

    total_input = sum(p.input_tokens for p in points)
    total_cache_read = sum(p.cache_read_tokens for p in points)

    return SummaryStats(
        total_llm_calls=sum(p.llm_calls for p in points),
        total_tool_calls=sum(p.tool_calls for p in points),
        total_input_tokens=total_input,
        total_output_tokens=sum(p.output_tokens for p in points),
        total_cache_read_tokens=total_cache_read,
        total_cost_usd=round(sum(p.cost_usd for p in points), 4),
        avg_latency_ms=round(sum(p.avg_latency_ms for p in points) / len(points), 1),
        cache_hit_rate=(
            round(total_cache_read / (total_input + total_cache_read), 3)
            if (total_input + total_cache_read) > 0
            else 0.0
        ),
    )


# ============================================================
# 路由
# ============================================================


@router.get("/timeseries", response_model=TimeseriesResponse)
async def get_timeseries(
    range: Literal["1h", "24h", "7d", "30d", "all"] = Query("24h"),
):
    range_seconds, bucket_seconds = _RANGE_CONFIG[range]

    if AGENT_MODE == "mock":
        points = _generate_mock_series(range_seconds, bucket_seconds)
        tool_totals: dict[str, int] = {}
        compaction_totals: dict[str, int] = {}
    else:
        store = get_store()
        raw_points, tool_totals, compaction_totals = store.query_timeseries(
            range_seconds, bucket_seconds
        )
        points = [
            MetricPoint(
                timestamp=p["timestamp"],
                llm_calls=p["llm_calls"],
                tool_calls=p["tool_calls"],
                input_tokens=p["input_tokens"],
                output_tokens=p["output_tokens"],
                cache_read_tokens=p["cache_read_tokens"],
                cache_write_tokens=p["cache_write_tokens"],
                cost_usd=p["cost_usd"],
                avg_latency_ms=p["avg_latency_ms"],
                tool_breakdown=p.get("tool_breakdown", {}),
                compaction_layers=p.get("compaction_layers", {}),
            )
            for p in raw_points
        ]

    summary = _summarize(points)

    return TimeseriesResponse(
        range=range,
        bucket_seconds=bucket_seconds,
        points=points,
        summary=summary,
        tool_totals=tool_totals,
        compaction_totals=compaction_totals,
    )


@router.get("/store-stats")
async def get_store_stats():
    """返回存储统计。"""
    try:
        store = get_store()
        return store.stats()
    except Exception as e:
        return {"error": str(e)}


@router.post("/prune")
async def prune_old_data(days: int = Query(30, ge=1)):
    """删除 N 天前的数据。"""
    try:
        store = get_store()
        removed = store.prune_older_than(days)
        return {"ok": True, "removed": removed}
    except Exception as e:
        return {"ok": False, "error": str(e)}
