"""Day 29: 并发与延迟优化。

- 子 Agent 并行探索：文件分析、测试执行
- 流式输出：减少首字节延迟
- 工具预取：预测下一步
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParallelTask:
    """一个并行任务。"""

    name: str
    fn: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


@dataclass
class ParallelResult:
    """并行执行结果。"""

    name: str
    result: Any
    duration_s: float
    error: str | None = None


def run_parallel(
    tasks: list[ParallelTask],
    max_workers: int = 4,
    timeout: float | None = None,
) -> list[ParallelResult]:
    """并行执行多个任务。

    适用场景：
    - 同时分析多个文件
    - 同时运行多个测试套件
    - 同时探索多个候选方案

    注意：Agent 的模型调用不应该并行（会稀释上下文），
    但工具执行可以并行。
    """
    results: list[ParallelResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for t in tasks:
            futures[ex.submit(t.fn, *t.args, **t.kwargs)] = t

        for fut in as_completed(futures, timeout=timeout):
            task = futures[fut]
            start = time.time()
            try:
                result = fut.result()
                results.append(
                    ParallelResult(
                        name=task.name,
                        result=result,
                        duration_s=time.time() - start,
                    )
                )
            except Exception as e:
                results.append(
                    ParallelResult(
                        name=task.name,
                        result=None,
                        duration_s=time.time() - start,
                        error=f"{type(e).__name__}: {e}",
                    )
                )

    return results


async def run_parallel_async(
    tasks: list[ParallelTask],
    timeout: float | None = None,
) -> list[ParallelResult]:
    """异步并行执行。用于 I/O 密集场景。"""

    async def _run_one(task: ParallelTask) -> ParallelResult:
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(task.fn):
                result = await task.fn(*task.args, **task.kwargs)
            else:
                result = task.fn(*task.args, **task.kwargs)
            return ParallelResult(
                name=task.name,
                result=result,
                duration_s=time.time() - start,
            )
        except Exception as e:
            return ParallelResult(
                name=task.name,
                result=None,
                duration_s=time.time() - start,
                error=f"{type(e).__name__}: {e}",
            )

    coros = [_run_one(t) for t in tasks]
    if timeout:
        return await asyncio.wait_for(asyncio.gather(*coros), timeout=timeout)
    return await asyncio.gather(*coros)


# ---------- 延迟优化 ----------


class ToolPrefetcher:
    """工具预取器。

    根据当前消息历史预测下一步可能调用的工具，
    提前开始执行（如果工具是幂等的）。

    适用场景：
    - 已知会调用的语义搜索（在 Agent 思考时预跑）
    - 已知会读取的文件（在 Agent 调用前预读）
    """

    def __init__(self, prefetch_fn: Callable, max_concurrent: int = 2):
        self.prefetch_fn = prefetch_fn
        self.max_concurrent = max_concurrent
        self._cache: dict[str, Any] = {}

    def predict_next_tools(self, messages: list) -> list[str]:
        """根据消息历史预测下一步工具。

        启发式：
        - 刚读完文件 → 预测下一步是 edit_file
        - 刚跑完测试失败 → 预测下一步是 read_file（读失败用例）
        - 刚开始任务 → 预测下一步是 semantic_search / repo_map
        """
        if not messages:
            return ["semantic_search", "repo_map"]

        last = messages[-1]
        last_name = getattr(last, "name", "") or ""

        if last_name in ("read_file", "sandbox_read"):
            return ["edit_file"]
        if last_name == "run_tests" and "fail" in str(last.content).lower():
            return ["read_file"]
        return []

    def prefetch(self, tool_name: str, **kwargs) -> None:
        """预取。结果缓存到 _cache，供实际调用时使用。"""
        if tool_name in self._cache:
            return
        try:
            self._cache[tool_name] = self.prefetch_fn(tool_name, **kwargs)
        except Exception:
            pass

    def get(self, tool_name: str) -> Any:
        """获取预取结果。"""
        return self._cache.pop(tool_name, None)
