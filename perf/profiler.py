"""Day 29: 性能剖析。

采集每个阶段的耗时分布，定位瓶颈。
"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Span:
    """一个耗时区间。"""
    name: str
    duration_s: float
    parent: str | None = None
    metadata: dict = field(default_factory=dict)


class Profiler:
    """轻量级剖析器。

    用法:
        profiler = Profiler()
        with profiler.span("agent.invoke"):
            with profiler.span("llm_call"):
                ...
    """

    def __init__(self):
        self.spans: list[Span] = []
        self._stack: list[tuple[str, float, dict]] = []

    @contextmanager
    def span(self, name: str, **metadata) -> Iterator[None]:
        """记录一个时间区间。"""
        parent = self._stack[-1][0] if self._stack else None
        start = time.perf_counter()
        self._stack.append((name, start, metadata))
        try:
            yield
        finally:
            _, start, meta = self._stack.pop()
            duration = time.perf_counter() - start
            self.spans.append(Span(
                name=name,
                duration_s=duration,
                parent=parent,
                metadata=meta,
            ))

    def summary(self) -> dict:
        """按 span 名聚合统计。"""
        by_name: dict[str, list[float]] = defaultdict(list)
        for s in self.spans:
            by_name[s.name].append(s.duration_s)

        result = {}
        for name, durations in by_name.items():
            result[name] = {
                "count": len(durations),
                "total_s": sum(durations),
                "avg_s": sum(durations) / len(durations),
                "max_s": max(durations),
                "min_s": min(durations),
            }
        return result

    def slowest_spans(self, limit: int = 10) -> list[Span]:
        """最慢的 span。"""
        return sorted(self.spans, key=lambda s: -s.duration_s)[:limit]

    def to_text(self) -> str:
        """人类可读的摘要。"""
        summary = self.summary()
        lines = ["性能剖析摘要", "=" * 60]
        for name, stats in sorted(
            summary.items(), key=lambda x: -x[1]["total_s"]
        ):
            lines.append(
                f"{name:40s} "
                f"count={stats['count']:4d} "
                f"total={stats['total_s']:7.3f}s "
                f"avg={stats['avg_s']:6.3f}s "
                f"max={stats['max_s']:6.3f}s"
            )
        return "\n".join(lines)