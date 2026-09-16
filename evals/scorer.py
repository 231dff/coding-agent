"""Day 28: 评分器。

从多个维度评分：
- 通过率：核心指标
- 效率：token 消耗、工具调用次数
- 缓存命中率：成本相关
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from evals.runner import TaskResult


@dataclass
class SuiteScore:
    """套件评分。"""

    total: int
    passed: int
    pass_rate: float
    avg_duration_s: float
    avg_input_tokens: float
    avg_output_tokens: float
    avg_cache_hit_rate: float
    by_category: dict[str, dict]

    def to_text(self) -> str:
        lines = [
            f"总计: {self.total}",
            f"通过: {self.passed} ({self.pass_rate:.1%})",
            f"平均耗时: {self.avg_duration_s:.2f}s",
            f"平均输入 token: {self.avg_input_tokens:.0f}",
            f"平均输出 token: {self.avg_output_tokens:.0f}",
            f"平均缓存命中率: {self.avg_cache_hit_rate:.1%}",
            "",
            "按类别:",
        ]
        for cat, stats in self.by_category.items():
            lines.append(f"  {cat}: {stats['passed']}/{stats['total']} ({stats['pass_rate']:.1%})")
        return "\n".join(lines)


def score_suite(results: list[TaskResult]) -> SuiteScore:
    """对整个套件评分。"""
    if not results:
        return SuiteScore(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, {})

    passed = sum(1 for r in results if r.passed)

    by_category: dict[str, list[TaskResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    category_stats = {}
    for cat, rs in by_category.items():
        category_stats[cat] = {
            "total": len(rs),
            "passed": sum(1 for r in rs if r.passed),
            "pass_rate": sum(1 for r in rs if r.passed) / len(rs),
            "avg_duration_s": mean(r.duration_s for r in rs),
        }

    return SuiteScore(
        total=len(results),
        passed=passed,
        pass_rate=passed / len(results),
        avg_duration_s=mean(r.duration_s for r in results),
        avg_input_tokens=mean(r.input_tokens for r in results),
        avg_output_tokens=mean(r.output_tokens for r in results),
        avg_cache_hit_rate=mean(r.cache_hit_rate for r in results),
        by_category=category_stats,
    )


def compare_baselines(
    current: list[TaskResult],
    baseline: list[TaskResult],
    regression_threshold: float = 0.10,
) -> tuple[bool, list[str]]:
    """对比基线与当前。

    Returns:
        (是否通过回归门禁, 消息列表)
    """
    current_score = score_suite(current)
    baseline_score = score_suite(baseline)

    messages: list[str] = []
    passed = True

    # 总体通过率下降超过阈值
    if current_score.pass_rate < baseline_score.pass_rate - regression_threshold:
        passed = False
        messages.append(
            f"❌ 通过率回归: {baseline_score.pass_rate:.1%} → {current_score.pass_rate:.1%}"
        )
    else:
        messages.append(
            f"✓ 通过率: {current_score.pass_rate:.1%} (基线 {baseline_score.pass_rate:.1%})"
        )

    # 类别级回归检查
    for cat, stats in current_score.by_category.items():
        if cat not in baseline_score.by_category:
            continue
        base = baseline_score.by_category[cat]["pass_rate"]
        curr = stats["pass_rate"]
        if curr < base - regression_threshold:
            passed = False
            messages.append(f"❌ [{cat}] 回归: {base:.1%} → {curr:.1%}")

    return passed, messages
