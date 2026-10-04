"""P3: 多 Agent 并行执行器。

管理者模式：
  - Manager（主 Agent）分解任务
  - ParallelExecutor 并行启动 N 个 Worker
  - 每个 Worker 独立上下文 + 共享沙箱
  - 一个 Worker 成功 → 触发 stop_all → 其余优雅退出

设计约束：
  - Worker 不共享主 Agent 轨迹（避免上下文污染）
  - 每个 Worker 用独立 thread_id（独立 checkpointer 状态）
  - Worker 的中间产物落在 shared/ 目录
  - Worker 的最终结果是 JSON 摘要，不是全量轨迹
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

WORKER_SYSTEM_PROMPT = """你是一个并行 Worker，负责独立完成一个具体子任务。

**约束**：
1. 只做被分配的子任务，不要越界处理其他任务
2. 每一步进展都要写到 {progress_file}
3. 完成后把结果以 JSON 写到 {result_file}，格式：
   {{"success": true, "summary": "...", "outputs": ["文件路径1", "文件路径2"]}}
4. 如果遇到无法解决的问题，写 {{"success": false, "error": "..."}} 到结果文件
5. 每完成一步，检查 {stop_flag} 是否存在——如果存在，说明其他 Worker 已成功，立即停止

**效率要求**：不要过度思考，专注完成子任务。最多 15 轮工具调用。
"""


@dataclass
class WorkerTask:
    task_id: str
    description: str
    agent_type: str = "general"


@dataclass
class WorkerResult:
    task_id: str
    success: bool
    summary: str = ""
    outputs: list[str] = field(default_factory=list)
    error: str = ""
    elapsed_s: float = 0.0
    tool_calls: int = 0


class ParallelExecutor:
    """并行 Worker 执行器。"""

    def __init__(
        self,
        llm,
        sandbox,
        base_dir: Path | str,
        tools: list[Any],
        max_workers: int = 3,
        max_iterations: int = 15,
    ):
        self.llm = llm
        self.sandbox = sandbox
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.shared_dir = self.base_dir / "shared"
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        self.tools = tools
        self.max_workers = max_workers
        self.max_iterations = max_iterations

        self._stop_event = threading.Event()
        self._results: dict[str, WorkerResult] = {}
        self._lock = threading.Lock()
        self._active = False

    # ---------- 公开 API ----------

    def run(self, tasks: list[WorkerTask]) -> list[WorkerResult]:
        """并行执行所有 Worker 任务。

        一个 Worker 成功 → 立即触发 stop_all → 其余 Worker 优雅退出。
        """
        if self._active:
            raise RuntimeError("已有并行任务在执行中")
        self._active = True
        self._stop_event.clear()
        self._results.clear()

        stop_flag = self.shared_dir / "_STOP"
        if stop_flag.exists():
            stop_flag.unlink()

        print(
            f"[parallel] 启动 {len(tasks)} 个 Worker（max_workers={self.max_workers}）",
            flush=True,
        )

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {
                    ex.submit(self._run_worker, t): t for t in tasks
                }
                for fut in as_completed(futures):
                    task = futures[fut]
                    try:
                        result = fut.result()
                    except Exception as e:
                        result = WorkerResult(
                            task_id=task.task_id,
                            success=False,
                            error=f"{type(e).__name__}: {e}",
                        )
                    with self._lock:
                        self._results[task.task_id] = result
                        if result.success:
                            print(
                                f"[parallel] Worker {task.task_id} 成功，触发 stop_all",
                                flush=True,
                            )
                            self._trigger_stop()
        finally:
            self._active = False

        return [
            self._results.get(t.task_id) for t in tasks if t.task_id in self._results
        ]

    def request_stop(self) -> None:
        """外部请求停止所有 Worker。"""
        self._trigger_stop()

    # ---------- 内部 ----------

    def _trigger_stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        (self.shared_dir / "_STOP").write_text(
            f"stopped at {time.time()}", encoding="utf-8"
        )

    def _run_worker(self, task: WorkerTask) -> WorkerResult:
        t0 = time.time()
        # ★ 独立 thread_id：每个 Worker 有独立的 checkpointer 状态
        session_id = f"worker-{task.task_id}-{uuid.uuid4().hex[:6]}"

        progress_file = self.shared_dir / f"progress-{task.task_id}.md"
        result_file = self.shared_dir / f"result-{task.task_id}.json"
        stop_flag = self.shared_dir / "_STOP"

        # 初始化进度
        progress_file.write_text(
            f"# Worker {task.task_id}\n\n子任务: {task.description}\n\n"
            f"状态: 启动中\n启动时间: {time.strftime('%H:%M:%S')}\n"
            f"thread_id: {session_id}\n",
            encoding="utf-8",
        )

        # 构造 Worker system prompt
        worker_prompt = WORKER_SYSTEM_PROMPT.format(
            progress_file=str(progress_file),
            result_file=str(result_file),
            stop_flag=str(stop_flag),
        )

        # 用受限的工具集（避免 Worker 再次 spawn）
        worker_tools = self._filter_worker_tools()

        print(f"[parallel] Worker {task.task_id} 启动 (tid={session_id})", flush=True)

        try:
            worker_agent = create_agent(
                model=self.llm,
                tools=worker_tools,
                system_prompt=worker_prompt,
            )

            invoke_messages = [
                HumanMessage(
                    content=(
                        f"## 你的子任务\n\n{task.description}\n\n"
                        f"## 执行约束\n"
                        f"- 完成后把结果写到 {result_file}\n"
                        f"- 每步更新进度到 {progress_file}\n"
                        f"- 见 {stop_flag} 就立即停止\n"
                    )
                )
            ]

            # 逐轮执行，每轮检查 stop_flag
            tool_calls = 0
            for step in range(self.max_iterations):
                if self._stop_event.is_set():
                    print(
                        f"[parallel] Worker {task.task_id} 收到停止信号",
                        flush=True,
                    )
                    self._append_progress(progress_file, "收到停止信号，优雅退出")
                    break

                if stop_flag.exists() and step > 0:
                    print(
                        f"[parallel] Worker {task.task_id} 检测到 _STOP 文件，退出",
                        flush=True,
                    )
                    self._append_progress(
                        progress_file, "检测到其他 Worker 已成功"
                    )
                    break

                # ★ 传入 thread_id，让 checkpointer 状态隔离
                result = worker_agent.invoke(
                    {"messages": invoke_messages},
                    config={
                        "configurable": {"thread_id": session_id},
                        "recursion_limit": 20,
                    },
                )
                new_messages = result.get("messages", [])

                last = new_messages[-1] if new_messages else None
                if last is not None and not getattr(last, "tool_calls", None):
                    tool_calls += sum(
                        1 for m in new_messages if getattr(m, "tool_calls", None)
                    )
                    break

                invoke_messages = new_messages
                tool_calls += sum(
                    1 for m in new_messages if getattr(m, "tool_calls", None)
                )

            # 读取 Worker 写的结果文件
            if result_file.exists():
                try:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                    return WorkerResult(
                        task_id=task.task_id,
                        success=bool(data.get("success", False)),
                        summary=data.get("summary", ""),
                        outputs=data.get("outputs", []),
                        error=data.get("error", ""),
                        elapsed_s=time.time() - t0,
                        tool_calls=tool_calls,
                    )
                except json.JSONDecodeError:
                    pass

            return WorkerResult(
                task_id=task.task_id,
                success=False,
                summary="Worker 未产出结果文件",
                error="result_file_missing",
                elapsed_s=time.time() - t0,
                tool_calls=tool_calls,
            )

        except Exception as e:
            self._append_progress(
                progress_file, f"异常: {type(e).__name__}: {e}"
            )
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error=f"{type(e).__name__}: {e}",
                elapsed_s=time.time() - t0,
            )

    def _filter_worker_tools(self) -> list[Any]:
        """Worker 可用工具：排除 spawn_workers 等递归工具。"""
        FORBIDDEN = {
            "spawn_workers",
            "get_worker_status",
            "stop_workers",
            "collect_results",
            "review_changes",
            "generate_summary_report",
        }
        return [t for t in self.tools if t.name not in FORBIDDEN]

    @staticmethod
    def _append_progress(progress_file: Path, line: str) -> None:
        try:
            with progress_file.open("a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%H:%M:%S')}] {line}")
        except Exception:
            pass


# ---------- 单例 ----------

_EXECUTOR: ParallelExecutor | None = None


def get_executor() -> ParallelExecutor | None:
    return _EXECUTOR


def set_executor(executor: ParallelExecutor) -> None:
    global _EXECUTOR
    _EXECUTOR = executor
