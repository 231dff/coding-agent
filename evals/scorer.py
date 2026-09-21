"""Day 28: 评分器。

从多个维度评分：
- 通过率：核心指标
- 效率：token 消耗、工具调用次数
- 缓存命中率：成本相关
- 成本：美元计价
- 延迟：P95 / P99
- 异常率：熔断/工具报错
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, quantiles

from evals.runner import TaskResult

# 模型定价表（每 1M tokens 的美元价格），可根据实际情况补充
MODEL_PRICES = {
    "openai:gpt-4o": {"input": 5.0, "output": 15.0},
    "openai:gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "anthropic:claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "default": {"input": 5.0, "output": 15.0},
}


@dataclass
class SuiteScore:
    """套件评分。"""

    total: int
    passed: int
    pass_rate: float
    avg_duration_s: float
    p95_duration_s: float
    p99_duration_s: float
    avg_input_tokens: float
    avg_output_tokens: float
    total_cost_usd: float
    avg_cost_usd: float
    avg_cache_hit_rate: float
    error_rate: float
    by_category: dict[str, dict]

    def to_text(self) -> str:
        lines = [
            f"总计: {self.total}",
            f"通过: {self.passed} ({self.pass_rate:.1%})",
            f"异常率: {self.error_rate:.1%}",
            f"平均耗时: {self.avg_duration_s:.2f}s",
            f"P95 耗时: {self.p95_duration_s:.2f}s",
            f"P99 耗时: {self.p99_duration_s:.2f}s",
            f"平均输入 token: {self.avg_input_tokens:.0f}",
            f"平均输出 token: {self.avg_output_tokens:.0f}",
            f"平均缓存命中率: {self.avg_cache_hit_rate:.1%}",
            f"总成本: ${self.total_cost_usd:.4f}",
            f"平均成本: ${self.avg_cost_usd:.4f}",
            "",
            "按类别:",
        ]
        for cat, stats in self.by_category.items():
            lines.append(
                f"  {cat}: {stats['passed']}/{stats['total']} "
                f"({stats['pass_rate']:.1%}) | "
                f"平均耗时 {stats['avg_duration_s']:.1f}s | "
                f"平均成本 ${stats['avg_cost_usd']:.4f}"
            )
        return "\n".join(lines)


def _calc_cost(input_tokens: int, output_tokens: int, model: str = "") -> float:
    """计算单次任务的成本（美元）。"""
    # 模糊匹配模型名，比如 "openai:gpt-4o-2024-11-20" 也能匹配到 "openai:gpt-4o"
    matched_price = MODEL_PRICES["default"]
    for key in MODEL_PRICES:
        if key != "default" and key in model:
            matched_price = MODEL_PRICES[key]
            break
    return (
        input_tokens / 1_000_000 * matched_price["input"]
        + output_tokens / 1_000_000 * matched_price["output"]
    )


def score_suite(results: list[TaskResult], model: str = "") -> SuiteScore:
    """对整个套件评分。"""
    if not results:
        return SuiteScore(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, {})

    passed = sum(1 for r in results if r.passed)
    errors = sum(1 for r in results if r.error)
    durations = sorted(r.duration_s for r in results)

    # 计算 P95 / P99
    if len(durations) >= 2:
        qs = quantiles(durations, n=100)
        p95 = qs[94] if len(qs) > 94 else durations[-1]
        p99 = qs[98] if len(qs) > 98 else durations[-1]
    else:
        p95 = p99 = durations[0] if durations else 0.0

    total_cost = sum(_calc_cost(r.input_tokens, r.output_tokens, model) for r in results)

    by_category: dict[str, list[TaskResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    category_stats = {}
    for cat, rs in by_category.items():
        cat_cost = sum(_calc_cost(r.input_tokens, r.output_tokens, model) for r in rs)
        category_stats[cat] = {
            "total": len(rs),
            "passed": sum(1 for r in rs if r.passed),
            "pass_rate": sum(1 for r in rs if r.passed) / len(rs),
            "avg_duration_s": mean(r.duration_s for r in rs),
            "avg_cost_usd": cat_cost / len(rs),
        }

    return SuiteScore(
        total=len(results),
        passed=passed,
        pass_rate=passed / len(results),
        avg_duration_s=mean(r.duration_s for r in results),
        p95_duration_s=p95,
        p99_duration_s=p99,
        avg_input_tokens=mean(r.input_tokens for r in results),
        avg_output_tokens=mean(r.output_tokens for r in results),
        total_cost_usd=total_cost,
        avg_cost_usd=total_cost / len(results),
        avg_cache_hit_rate=mean(r.cache_hit_rate for r in results),
        error_rate=errors / len(results),
        by_category=category_stats,
    )


def compare_baselines(
    current: list[TaskResult],
    baseline: list[TaskResult],
    model: str = "",
    regression_threshold: float = 0.10,
    cost_threshold: float = 0.20,
) -> tuple[bool, list[str]]:
    """对比基线与当前。"""
    current_score = score_suite(current, model)
    baseline_score = score_suite(baseline, model)

    messages: list[str] = []
    passed = True

    # 1. 通过率回归
    if current_score.pass_rate < baseline_score.pass_rate - regression_threshold:
        passed = False
        messages.append(
            f"❌ 通过率回归: {baseline_score.pass_rate:.1%} → {current_score.pass_rate:.1%}"
        )
    else:
        messages.append(
            f"✓ 通过率: {current_score.pass_rate:.1%} (基线 {baseline_score.pass_rate:.1%})"
        )

    # 2. 成本回归（涨幅超过 20% 告警）
    if baseline_score.avg_cost_usd > 0:
        cost_change = (
            current_score.avg_cost_usd - baseline_score.avg_cost_usd
        ) / baseline_score.avg_cost_usd
        if cost_change > cost_threshold:
            passed = False
            messages.append(
                f"❌ 成本回归: ${baseline_score.avg_cost_usd:.4f} → "
                f"${current_score.avg_cost_usd:.4f} (+{cost_change:.1%})"
            )
        else:
            messages.append(
                f"✓ 成本: ${current_score.avg_cost_usd:.4f} "
                f"(基线 ${baseline_score.avg_cost_usd:.4f})"
            )

    # 3. 异常率监控（超过 10% 告警）
    if current_score.error_rate > 0.10:
        passed = False
        messages.append(f"❌ 异常率过高: {current_score.error_rate:.1%}")

    # 4. 类别级回归
    for cat, stats in current_score.by_category.items():
        if cat not in baseline_score.by_category:
            continue
        base = baseline_score.by_category[cat]["pass_rate"]
        curr = stats["pass_rate"]
        if curr < base - regression_threshold:
            passed = False
            messages.append(f"❌ [{cat}] 回归: {base:.1%} → {curr:.1%}")

    return passed, messages
