"""Day 28: 评测 CLI。

用法:
    python -m evals --model openai:gpt-5.5
    python -m evals --parallel --max-workers 4
    python -m evals --baseline evals/baseline.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.dataset import load_tasks
from evals.runner import run_suite
from evals.report import generate_markdown_report, save_results, load_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Coding Agent 评测")
    parser.add_argument("--model", default="openai:gpt-5.5")
    parser.add_argument("--tasks-dir", default="evals/tasks")
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--baseline", default="", help="基线 JSON 路径")
    parser.add_argument("--output", default="docs/eval_report.md")
    parser.add_argument("--results-json", default="evals/latest_results.json")
    parser.add_argument("--filter-category", default="")
    args = parser.parse_args()

    # 加载任务
    tasks = load_tasks(args.tasks_dir)
    if args.filter_category:
        tasks = [t for t in tasks if t.category == args.filter_category]

    if not tasks:
        print("没有找到评测任务", file=sys.stderr)
        return 1

    print(f"加载 {len(tasks)} 个任务，模型: {args.model}")

    # 进度显示
    def on_progress(done: int, total: int, task_id: str, passed: bool):
        status = "✓" if passed else "✗"
        print(f"  [{done}/{total}] {status} {task_id}")

    # 运行
    results = run_suite(
        tasks,
        model=args.model,
        parallel=args.parallel,
        max_workers=args.max_workers,
        progress_callback=on_progress,
    )

    # 加载基线
    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = load_results(args.baseline)

    # 生成报告
    report = generate_markdown_report(results, baseline, args.output)
    print("\n" + "=" * 60)
    print(report[:2000])
    print("=" * 60)
    print(f"\n报告已写入: {args.output}")

    save_results(results, args.results_json)

    # 回归门禁
    if baseline:
        from evals.scorer import compare_baselines
        passed, _ = compare_baselines(results, baseline)
        return 0 if passed else 2

    return 0


if __name__ == "__main__":
    sys.exit(main())