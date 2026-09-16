"""Day 28: 报告生成。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from evals.runner import TaskResult
from evals.scorer import SuiteScore, score_suite


def generate_markdown_report(
    results: list[TaskResult],
    baseline: list[TaskResult] | None = None,
    output_path: str | Path = "docs/eval_report.md",
) -> str:
    """生成 Markdown 格式的评测报告。"""
    score = score_suite(results)

    lines = [
        "# 评测报告",
        "",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 总体",
        "",
        "```",
        score.to_text(),
        "```",
        "",
    ]

    if baseline:
        from evals.scorer import compare_baselines
        passed, msgs = compare_baselines(results, baseline)
        lines.extend([
            "## 回归检查",
            "",
            f"状态: {'✓ 通过' if passed else '❌ 未通过'}",
            "",
            "```",
            *msgs,
            "```",
            "",
        ])

    lines.extend([
        "## 详细结果",
        "",
        "| 任务 | 类别 | 结果 | 耗时 | 输入 tokens | 工具调用 |",
        "|------|------|------|------|-------------|----------|",
    ])

    for r in sorted(results, key=lambda x: (x.category, x.task_id)):
        status = "✓" if r.passed else "✗"
        tools_str = ", ".join(r.tool_calls[:5])
        if len(r.tool_calls) > 5:
            tools_str += f" (+{len(r.tool_calls) - 5})"
        lines.append(
            f"| {r.task_id} | {r.category} | {status} | "
            f"{r.duration_s:.1f}s | {r.input_tokens} | {tools_str} |"
        )

    lines.append("")

    # 失败详情
    failures = [r for r in results if not r.passed]
    if failures:
        lines.extend(["## 失败详情", ""])
        for r in failures:
            lines.append(f"### {r.task_id}")
            lines.append("")
            if r.error:
                lines.append(f"**错误**: {r.error}")
                lines.append("")
            if r.assert_error:
                lines.append("**断言失败**:")
                lines.append("```")
                lines.append(r.assert_error[:500])
                lines.append("```")
            lines.append("")

    content = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    return content


def save_results(results: list[TaskResult], path: str | Path) -> None:
    """保存原始结果到 JSON。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_results(path: str | Path) -> list[TaskResult]:
    """加载原始结果。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TaskResult(**item) for item in data]