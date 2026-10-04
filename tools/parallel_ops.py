"""P3: 并行 Worker 工具。

暴露给主 Agent：
  - spawn_workers(tasks_json)  — 并行启动 N 个 Worker
  - get_worker_status(task_id) — 查询单个 Worker 进度
  - stop_workers()             — 手动终止所有 Worker
  - collect_results()          — 收集所有结果
"""

from __future__ import annotations

import json

from langchain.tools import tool

from agent.parallel import WorkerTask, get_executor


@tool
def spawn_workers(tasks_json: str) -> str:
    """并行启动 N 个 Worker，各自独立完成一个子任务。

    **只在子任务真正独立时使用**（比如同时分析 5 个不相关的模块）。
    有依赖关系的任务应串行执行。

    一个 Worker 成功后，其余 Worker 会自动收到停止信号并优雅退出。

    Args:
        tasks_json: JSON 数组字符串，每项格式：
            [{"task_id": "m1", "description": "分析模块 A 的测试覆盖率"},
             {"task_id": "m2", "description": "分析模块 B 的测试覆盖率"}]

    Returns:
        JSON 字符串，包含所有 Worker 的结果摘要：
            {"results": [{"task_id": "...", "success": true, "summary": "...",
                          "outputs": ["..."], "error": "", "elapsed_s": 12.3}]}
    """
    executor = get_executor()
    if executor is None:
        return json.dumps({"error": "ParallelExecutor 未初始化"}, ensure_ascii=False)

    try:
        raw = json.loads(tasks_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"tasks_json 解析失败: {e}"}, ensure_ascii=False)

    if not isinstance(raw, list) or not raw:
        return json.dumps({"error": "tasks_json 必须是非空数组"}, ensure_ascii=False)

    tasks = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        task_id = item.get("task_id") or f"task-{len(tasks)}"
        desc = item.get("description", "")
        if not desc:
            continue
        tasks.append(
            WorkerTask(
                task_id=task_id,
                description=desc,
                agent_type=item.get("agent_type", "general"),
            )
        )

    if not tasks:
        return json.dumps({"error": "没有有效的任务"}, ensure_ascii=False)

    results = executor.run(tasks)

    payload = {
        "results": [
            {
                "task_id": r.task_id,
                "success": r.success,
                "summary": r.summary,
                "outputs": r.outputs,
                "error": r.error,
                "elapsed_s": round(r.elapsed_s, 1),
                "tool_calls": r.tool_calls,
            }
            for r in results
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def get_worker_status(task_id: str) -> str:
    """查询单个 Worker 的进度（读进度文件）。

    Args:
        task_id: Worker 的 task_id。
    """
    executor = get_executor()
    if executor is None:
        return json.dumps({"error": "ParallelExecutor 未初始化"}, ensure_ascii=False)

    progress_file = executor.shared_dir / f"progress-{task_id}.md"
    result_file = executor.shared_dir / f"result-{task_id}.json"

    payload = {"task_id": task_id}
    if progress_file.exists():
        payload["progress"] = progress_file.read_text(encoding="utf-8")[-1500:]
    else:
        payload["progress"] = "(无进度文件)"

    if result_file.exists():
        try:
            payload["result"] = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            payload["result"] = "(结果文件解析失败)"

    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def stop_workers() -> str:
    """手动终止所有正在运行的 Worker。

    通常在发现整体方向不对、需要重新规划时调用。
    正常情况下不需要——Worker 成功后会自动触发终止。
    """
    executor = get_executor()
    if executor is None:
        return json.dumps({"error": "ParallelExecutor 未初始化"}, ensure_ascii=False)
    executor.request_stop()
    return json.dumps({"ok": True, "message": "已发送停止信号"}, ensure_ascii=False)


@tool
def collect_results() -> str:
    """收集所有 Worker 的结果（从 shared/ 目录读 result-*.json）。

    适用于 `spawn_workers` 超时或异常退出后，手动抢救已完成的结果。
    """
    executor = get_executor()
    if executor is None:
        return json.dumps({"error": "ParallelExecutor 未初始化"}, ensure_ascii=False)

    results = []
    for f in sorted(executor.shared_dir.glob("result-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["task_id"] = f.stem.replace("result-", "")
            results.append(data)
        except Exception:
            continue

    return json.dumps({"results": results}, ensure_ascii=False, indent=2)


PARALLEL_TOOLS = [
    "spawn_workers",
    "get_worker_status",
    "stop_workers",
    "collect_results",
]
