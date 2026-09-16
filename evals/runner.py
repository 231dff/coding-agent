"""Day 28: 评测批量运行器。

对每个任务：
1. 创建临时工作区
2. 写入 setup 文件
3. 启动 Agent
4. 执行任务描述
5. 检查成功断言
6. 收集指标
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from agent.config import AgentConfig
from agent.core import build_agent
from evals.dataset import EvalTask, run_assert
from observability.metrics import MetricsCollector


@dataclass
class TaskResult:
    """单个任务的执行结果。"""
    task_id: str
    category: str
    passed: bool
    duration_s: float
    tool_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_rate: float = 0.0
    error: str | None = None
    assert_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "passed": self.passed,
            "duration_s": round(self.duration_s, 2),
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_hit_rate": round(self.cache_hit_rate, 3),
            "error": self.error,
            "assert_error": self.assert_error,
        }


def run_task(
    task: EvalTask,
    model: str = "openai:gpt-5.5",
    keep_workspace: bool = False,
) -> TaskResult:
    """运行单个评测任务。"""
    ws = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    started = time.time()
    result = TaskResult(
        task_id=task.id,
        category=task.category,
        passed=False,
        duration_s=0.0,
    )

    try:
        # 1. 写入 setup 文件
        for path, content in task.setup.items():
            p = ws / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        # 2. 构建 Agent
        cfg = AgentConfig(workspace=str(ws), model=model, verbose=False)
        metrics = MetricsCollector(session_id=task.id)

        with build_agent(cfg) as rt:
            # 3. 执行任务
            response = rt.agent.invoke(
                {"messages": [{"role": "user", "content": task.description}]},
                config={"configurable": {"thread_id": f"eval-{task.id}"}},
            )

            # 4. 收集工具调用序列
            for msg in response.get("messages", []):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        result.tool_calls.append(tc["name"])

            # 5. 收集指标
            snap = metrics.snapshot()
            result.input_tokens = snap["input_tokens"]
            result.output_tokens = snap["output_tokens"]
            result.cache_hit_rate = snap["cache_hit_rate"]

        # 6. 检查成功断言
        passed, assert_err = run_assert(task.success_assert, ws)
        result.passed = passed
        result.assert_error = assert_err or None

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.assert_error = traceback.format_exc()[-1000:]
    finally:
        result.duration_s = time.time() - started
        if not keep_workspace:
            shutil.rmtree(ws, ignore_errors=True)

    return result


def run_suite(
    tasks: list[EvalTask],
    model: str = "openai:gpt-5.5",
    parallel: bool = False,
    max_workers: int = 4,
    progress_callback=None,
) -> list[TaskResult]:
    """运行整个评测套件。

    Args:
        tasks: 任务列表。
        model: 模型标识。
        parallel: 是否并行执行。
        max_workers: 并行度。
        progress_callback: 进度回调 (done, total, task_id, passed)。
    """
    results: list[TaskResult] = []

    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(run_task, t, model): t for t in tasks}
            for i, fut in enumerate(as_completed(futures), 1):
                r = fut.result()
                results.append(r)
                if progress_callback:
                    progress_callback(i, len(tasks), r.task_id, r.passed)
    else:
        for i, task in enumerate(tasks, 1):
            r = run_task(task, model)
            results.append(r)
            if progress_callback:
                progress_callback(i, len(tasks), r.task_id, r.passed)

    return results