"""Day 28: 报告生成。"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from evals.runner import TaskResult
from evals.scorer import score_suite


def generate_markdown_report(
    results: list[TaskResult],
    baseline: list[TaskResult] | None = None,
    output_path: str | Path = "docs/eval_report.md",
    model: str = "",
) -> str:
    """生成 Markdown 格式的评测报告。"""
    score = score_suite(results, model)

    lines = [
        "# 📊 Coding Agent 评测报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**模型**: `{model or 'default'}`",
        "",
        "## 🎯 核心指标",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| **任务通过率** | **{score.pass_rate:.1%}** ({score.passed}/{score.total}) |",
        f"| 异常率 | {score.error_rate:.1%} |",
        f"| 平均耗时 | {score.avg_duration_s:.2f}s |",
        f"| P95 耗时 | {score.p95_duration_s:.2f}s |",
        f"| 平均输入 Token | {score.avg_input_tokens:.0f} |",
        f"| 平均输出 Token | {score.avg_output_tokens:.0f} |",
        f"| 平均缓存命中率 | {score.avg_cache_hit_rate:.1%} |",
        f"| **总成本** | **${score.total_cost_usd:.4f}** |",
        f"| **平均单任务成本** | **${score.avg_cost_usd:.4f}** |",
        "",
        "## 📂 分类别结果",
        "",
        "| 类别 | 通过率 | 平均耗时 | 平均成本 |",
        "|------|--------|----------|----------|",
    ]
    for cat, stats in score.by_category.items():
        lines.append(
            f"| {cat} | {stats['pass_rate']:.1%} ({stats['passed']}/{stats['total']}) | "
            f"{stats['avg_duration_s']:.1f}s | ${stats['avg_cost_usd']:.4f} |"
        )
    lines.append("")

    if baseline:
        from evals.scorer import compare_baselines

        passed, msgs = compare_baselines(results, baseline, model)
        lines.extend(
            [
                "## 🔍 回归检查",
                "",
                f"**状态**: {'✅ 通过' if passed else '❌ 未通过'}",
                "",
                "```",
                *msgs,
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## 📋 详细结果",
            "",
            "| 任务 | 类别 | 结果 | 耗时 | 输入 Token | 输出 Token | 工具调用 |",
            "|------|------|------|------|-----------|-----------|----------|",
        ]
    )

    for r in sorted(results, key=lambda x: (x.category, x.task_id)):
        status = "✅" if r.passed else "❌"
        tools_str = ", ".join(r.tool_calls[:5])
        if len(r.tool_calls) > 5:
            tools_str += f" (+{len(r.tool_calls) - 5})"
        lines.append(
            f"| {r.task_id} | {r.category} | {status} | "
            f"{r.duration_s:.1f}s | {r.input_tokens} | {r.output_tokens} | {tools_str} |"
        )

    lines.append("")

    # ---------- 失败详情（同时显示 error 和 assert_error） ----------
    failures = [r for r in results if not r.passed]
    if failures:
        lines.extend(["## ❌ 失败详情", ""])
        for r in failures:
            lines.append(f"### {r.task_id}")
            lines.append("")

            # 1. 执行错误（异常/崩溃）
            if r.error:
                lines.append("**执行错误**:")
                lines.append("```")
                lines.append(r.error[:800])
                lines.append("```")
                lines.append("")

            # 2. 断言失败
            if r.assert_error:
                lines.append("**断言失败**:")
                lines.append("```")
                lines.append(r.assert_error[:800])
                lines.append("```")
                lines.append("")

            # 3. 两个都没有 → 显示诊断信息
            if not r.error and not r.assert_error:
                lines.append(
                    f"**诊断**: 任务返回 False 但无错误信息。\n"
                    f"- 工具调用次数: {len(r.tool_calls)}\n"
                    f"- 工具序列: `{r.tool_calls}`"
                )
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


def export_csv(results: list[TaskResult], path: str | Path = "evals/results.csv") -> None:
    """导出 CSV，方便用 Excel 或 Streamlit 画图。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not results:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].to_dict().keys())
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_dict())


def write_github_step_summary(markdown_content: str) -> None:
    """将报告写入 GitHub Actions Step Summary，CI 里直接可见。"""
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(markdown_content)