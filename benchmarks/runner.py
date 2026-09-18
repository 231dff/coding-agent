"""基准运行器。

用法：
    python -m benchmarks.runner               # 跑全部任务
    python -m benchmarks.runner --task read_only
    python -m benchmarks.runner --save        # 保存为基线
    python -m benchmarks.runner --compare     # 与基线对比
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from benchmarks.tasks import TASKS, BenchTask

BASELINE_PATH = Path(__file__).parent / "baseline.json"


@dataclass
class TaskResult:
    """单个任务的运行结果。"""

    name: str
    elapsed_s: float
    exit_code: int
    success: bool
    verify_passed: bool = False
    stdout_len: int = 0
    stderr_len: int = 0
    error: str = ""


@dataclass
class BenchResult:
    """整体基准结果。"""

    timestamp: float
    model: str
    total_elapsed_s: float
    tasks: list[TaskResult] = field(default_factory=list)


# ============================================================
# 运行
# ============================================================


def run_task(
    task: BenchTask,
    project_dir: Path,
    timeout: int | None = None,
) -> TaskResult:
    """跑一个任务。"""
    # setup
    if task.setup:
        try:
            task.setup(project_dir)
        except Exception as e:
            return TaskResult(
                name=task.name,
                elapsed_s=0,
                exit_code=-1,
                success=False,
                error=f"setup failed: {e}",
            )

    # 跑 agent
    start = time.time()
    try:
        result = subprocess.run(
            ["coding-agent", task.description],
            cwd=str(project_dir),
            capture_output=True,
            timeout=timeout or task.timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - start

        # verify
        verify_ok = False
        if task.verify:
            try:
                verify_ok = task.verify(project_dir)
            except Exception:
                verify_ok = False

        return TaskResult(
            name=task.name,
            elapsed_s=round(elapsed, 2),
            exit_code=result.returncode,
            success=result.returncode == 0,
            verify_passed=verify_ok,
            stdout_len=len(result.stdout),
            stderr_len=len(result.stderr),
        )

    except subprocess.TimeoutExpired:
        return TaskResult(
            name=task.name,
            elapsed_s=float(timeout or task.timeout),
            exit_code=-1,
            success=False,
            error="timeout",
        )
    except Exception as e:
        return TaskResult(
            name=task.name,
            elapsed_s=time.time() - start,
            exit_code=-1,
            success=False,
            error=str(e),
        )


def run_all(
    project_dir: Path,
    task_names: list[str] | None = None,
    model: str = "",
) -> BenchResult:
    """跑所有任务。"""
    tasks = [t for t in TASKS if task_names is None or t.name in task_names]

    start = time.time()
    results: list[TaskResult] = []

    for task in tasks:
        print(f"[bench] running: {task.name} ({task.description!r})")
        r = run_task(task, project_dir)
        results.append(r)
        status = "✅" if (r.success and r.verify_passed) else "❌"
        print(
            f"[bench]   {status} elapsed={r.elapsed_s}s exit={r.exit_code} verify={r.verify_passed}"
        )

    return BenchResult(
        timestamp=time.time(),
        model=model,
        total_elapsed_s=round(time.time() - start, 2),
        tasks=results,
    )


# ============================================================
# 保存 / 对比
# ============================================================


def save_baseline(result: BenchResult) -> None:
    data = asdict(result)
    BASELINE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[bench] baseline saved: {BASELINE_PATH}")


def load_baseline() -> BenchResult | None:
    if not BASELINE_PATH.is_file():
        return None
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        return BenchResult(
            timestamp=data["timestamp"],
            model=data.get("model", ""),
            total_elapsed_s=data["total_elapsed_s"],
            tasks=[TaskResult(**t) for t in data["tasks"]],
        )
    except Exception:
        return None


def compare(current: BenchResult, baseline: BenchResult) -> int:
    """对比当前与基线。返回退出码（0=正常，1=退化）。"""
    print()
    print("=" * 60)
    print("Benchmark Comparison")
    print("=" * 60)

    base_by_name = {t.name: t for t in baseline.tasks}
    regressions: list[str] = []

    for t in current.tasks:
        base = base_by_name.get(t.name)
        if base is None:
            print(f"[{t.name}] NEW (no baseline)")
            continue

        delta = t.elapsed_s - base.elapsed_s
        pct = (delta / base.elapsed_s * 100) if base.elapsed_s > 0 else 0

        status = "✅"
        if pct > 20:
            status = "❌"
            regressions.append(f"{t.name}: {base.elapsed_s}s → {t.elapsed_s}s (+{pct:.1f}%)")
        elif pct < -20:
            status = "🚀"

        print(
            f"[{t.name:20s}] {status} {base.elapsed_s:6.2f}s → {t.elapsed_s:6.2f}s ({pct:+5.1f}%)"
        )

        # verify 从 True → False 也算退化
        if base.verify_passed and not t.verify_passed:
            regressions.append(f"{t.name}: verify_passed {base.verify_passed} → {t.verify_passed}")

    print()
    if regressions:
        print(f"⚠️  {len(regressions)} regression(s):")
        for r in regressions:
            print(f"   - {r}")
        return 1

    print("✅ No regressions")
    return 0


# ============================================================
# CLI
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", nargs="*", help="只跑指定任务")
    parser.add_argument("--project", default=".", help="项目目录")
    parser.add_argument("--model", default="", help="模型名（仅记录）")
    parser.add_argument("--save", action="store_true", help="保存为基线")
    parser.add_argument("--compare", action="store_true", help="与基线对比")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    if not project_dir.is_dir():
        print(f"ERROR: 项目目录不存在: {project_dir}", file=sys.stderr)
        return 1

    result = run_all(project_dir, args.task, args.model)

    if args.save:
        save_baseline(result)

    if args.compare:
        baseline = load_baseline()
        if baseline is None:
            print("[bench] 无基线，跳过对比")
            return 0
        return compare(result, baseline)

    return 0


if __name__ == "__main__":
    sys.exit(main())
