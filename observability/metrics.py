"""Day 27: 指标采集。

采集维度：
- 每轮：token 消耗、工具调用次数、延迟
- 每工具：调用次数、成功/失败、平均耗时
- 每会话：总成本、缓存命中率、压缩次数
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallRecord:
    """一次模型调用记录。"""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration_s: float = 0.0
    success: bool = True
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolCallRecord:
    """一次工具调用记录。"""

    tool_name: str
    duration_s: float
    success: bool
    args_size: int = 0
    result_size: int = 0
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """指标采集器（线程安全）。

    设计：
    - 内存中累加，定期 flush 到持久化层
    - 计数器是无锁累加（int 的 += 在 CPython 下原子）
    - 复杂统计（分位数）单独加锁
    """

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.started_at = time.time()

        # 计数器
        self.llm_calls = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0

        # 明细
        self._llm_records: list[CallRecord] = []
        self._tool_records: list[ToolCallRecord] = []
        self._tool_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "failures": 0, "total_duration": 0.0}
        )

        self._lock = threading.Lock()

    def record_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        duration_s: float = 0.0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """记录一次模型调用。"""
        record = CallRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            duration_s=duration_s,
            success=success,
            error=error,
        )

        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.cache_write_tokens += cache_write_tokens

        with self._lock:
            self._llm_records.append(record)

    def record_tool_call(
        self,
        tool_name: str,
        duration_s: float,
        success: bool,
        args_size: int = 0,
        result_size: int = 0,
    ) -> None:
        """记录一次工具调用。"""
        record = ToolCallRecord(
            tool_name=tool_name,
            duration_s=duration_s,
            success=success,
            args_size=args_size,
            result_size=result_size,
        )

        self.tool_calls += 1
        stats = self._tool_stats[tool_name]
        stats["count"] += 1
        stats["total_duration"] += duration_s
        if not success:
            stats["failures"] += 1

        with self._lock:
            self._tool_records.append(record)

    # ---------- 统计聚合 ----------

    def cache_hit_rate(self) -> float:
        """缓存命中率。"""
        total = self.input_tokens + self.cache_read_tokens
        if total == 0:
            return 0.0
        return self.cache_read_tokens / total

    def avg_llm_duration(self) -> float:
        """平均模型调用延迟。"""
        with self._lock:
            if not self._llm_records:
                return 0.0
            return sum(r.duration_s for r in self._llm_records) / len(self._llm_records)

    def tool_stats(self) -> dict[str, dict[str, Any]]:
        """每工具的统计。"""
        result = {}
        for name, s in self._tool_stats.items():
            count = s["count"]
            result[name] = {
                "count": count,
                "failures": s["failures"],
                "failure_rate": s["failures"] / count if count else 0.0,
                "avg_duration_s": s["total_duration"] / count if count else 0.0,
            }
        return result

    def slowest_tools(self, limit: int = 5) -> list[tuple[str, float]]:
        """最慢的工具。"""
        stats = self.tool_stats()
        items = [(name, s["avg_duration_s"]) for name, s in stats.items()]
        items.sort(key=lambda x: -x[1])
        return items[:limit]

    def snapshot(self) -> dict:
        """完整快照。"""
        return {
            "session_id": self.session_id,
            "elapsed_s": time.time() - self.started_at,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_hit_rate": self.cache_hit_rate(),
            "avg_llm_duration_s": self.avg_llm_duration(),
            "tools": self.tool_stats(),
        }
