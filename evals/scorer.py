"""Day 28: 评分器。

从多个维度评分：
- 通过率：核心指标
- 效率：token 消耗、工具调用次数
- 缓存命中率：成本相关
- 成本：美元计价
- 延迟：P95 / P99
- 异常率：熔断/工具报错

回归门禁：
- 总体通过率下降超过阈值 → 失败
- 成本涨幅超过阈值 → 失败
- 异常率过高 → 失败
- 类别级回归：仅对任务数 >= min_tasks_for_category 的类别检查
  （小样本类别波动大，容易误报）
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, quantiles

from evals.runner import TaskResult

# ============================================================
# 模型定价表（每 1M tokens 的美元价格）
# ============================================================
MODEL_PRICES: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Anthropic
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    # Qwen（DashScope 阿里云）
    "qwen-max": {"input": 1.60, "output": 6.40},
    "qwen-plus": {"input": 0.40, "output": 1.20},
    "qwen-turbo": {"input": 0.05, "output": 0.20},
    "qwen3.7-flash": {"input": 0.10, "output": 0.40},
    "qwen3-max": {"input": 1.60, "output": 6.40},
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # 兜底
    "default": {"input": 1.00, "output": 3.00},
}


# ============================================================
# 数据类
# ============================================================


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


# ============================================================
# 工具函数
# ============================================================


def _calc_cost(input_tokens: int, output_tokens: int, model: str = "") -> float:
    """计算单次任务的成本（美元）。

    匹配策略：优先精确匹配，再前缀匹配，最后兜底 default。
    """
    if not model:
        matched = MODEL_PRICES["default"]
    else:
        # 去掉 "provider:" 前缀
        model_name = model.split(":", 1)[-1] if ":" in model else model

        # 精确匹配
        matched = MODEL_PRICES.get(model_name)
        if matched is None:
            # 前缀匹配（比如 "gpt-4o-2024-11-20" 匹配 "gpt-4o"）
            matched = MODEL_PRICES["default"]
            for key, price in MODEL_PRICES.items():
                if key == "default":
                    continue
                if model_name.startswith(key) or key in model_name:
                    matched = price
                    break

    return (
        input_tokens / 1_000_000 * matched["input"] + output_tokens / 1_000_000 * matched["output"]
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """从已排序的列表里取百分位数（pct 是 0-100）。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    # 用 statistics.quantiles 更准，但需要至少 2 个元素
    try:
        # n=100 产生 99 个分割点
        qs = quantiles(sorted_values, n=100, method="inclusive")
        idx = int(pct) - 1  # 0-based
        if 0 <= idx < len(qs):
            return qs[idx]
    except Exception:
        pass

    # 兜底：线性插值
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


# ============================================================
# 主评分函数
# ============================================================


def score_suite(results: list[TaskResult], model: str = "") -> SuiteScore:
    """对整个套件评分。"""
    if not results:
        return SuiteScore(
            total=0,
            passed=0,
            pass_rate=0.0,
            avg_duration_s=0.0,
            p95_duration_s=0.0,
            p99_duration_s=0.0,
            avg_input_tokens=0.0,
            avg_output_tokens=0.0,
            total_cost_usd=0.0,
            avg_cost_usd=0.0,
            avg_cache_hit_rate=0.0,
            error_rate=0.0,
            by_category={},
        )

    passed = sum(1 for r in results if r.passed)
    errors = sum(1 for r in results if r.error)

    durations = sorted(r.duration_s for r in results)
    p95 = _percentile(durations, 95)
    p99 = _percentile(durations, 99)

    total_cost = sum(_calc_cost(r.input_tokens, r.output_tokens, model) for r in results)

    # 按类别分组
    by_category: dict[str, list[TaskResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    category_stats: dict[str, dict] = {}
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


# ============================================================
# 回归对比（带小样本类别保护）
# ============================================================


def compare_baselines(
    current: list[TaskResult],
    baseline: list[TaskResult],
    model: str = "",
    regression_threshold: float = 0.10,
    cost_threshold: float = 0.20,
    error_rate_threshold: float = 0.20,
    min_tasks_for_category: int = 3,
) -> tuple[bool, list[str]]:
    """对比基线与当前。

    Args:
        current: 当前结果。
        baseline: 基线结果。
        model: 模型名（用于成本计算）。
        regression_threshold: 通过率允许下降的比例（默认 10%）。
        cost_threshold: 成本允许上涨的比例（默认 20%）。
        error_rate_threshold: 异常率上限（默认 20%）。
        min_tasks_for_category: 类别至少多少任务才做类别级门禁（默认 3）。

    Returns:
        (是否通过门禁, 消息列表)
    """
    current_score = score_suite(current, model)
    baseline_score = score_suite(baseline, model)

    messages: list[str] = []
    passed = True

    # ---------- 1. 总体通过率回归 ----------
    if baseline_score.pass_rate > 0:
        drop = baseline_score.pass_rate - current_score.pass_rate
        if drop > regression_threshold:
            passed = False
            messages.append(
                f"❌ 通过率回归: {baseline_score.pass_rate:.1%} → "
                f"{current_score.pass_rate:.1%} (下降 {drop:.1%})"
            )
        else:
            messages.append(
                f"✓ 通过率: {current_score.pass_rate:.1%} (基线 {baseline_score.pass_rate:.1%})"
            )
    else:
        messages.append(f"· 通过率: {current_score.pass_rate:.1%}（基线为空或为 0）")

    # ---------- 2. 成本回归 ----------
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
            sign = "+" if cost_change >= 0 else ""
            messages.append(
                f"✓ 成本: ${current_score.avg_cost_usd:.4f} "
                f"(基线 ${baseline_score.avg_cost_usd:.4f}, {sign}{cost_change:.1%})"
            )
    else:
        messages.append(f"· 成本: ${current_score.avg_cost_usd:.4f}（基线为空或为 0）")

    # ---------- 3. 异常率 ----------
    if current_score.error_rate > error_rate_threshold:
        passed = False
        messages.append(
            f"❌ 异常率过高: {current_score.error_rate:.1%} (阈值 {error_rate_threshold:.1%})"
        )
    else:
        messages.append(f"✓ 异常率: {current_score.error_rate:.1%}")

    # ---------- 4. 类别级回归（小样本跳过） ----------
    checked_categories: list[str] = []
    skipped_categories: list[str] = []

    for cat, curr_stats in current_score.by_category.items():
        if cat not in baseline_score.by_category:
            skipped_categories.append(f"{cat}(新类别)")
            continue

        base_stats = baseline_score.by_category[cat]

        # ★ 关键：小样本类别跳过门禁
        if base_stats["total"] < min_tasks_for_category:
            skipped_categories.append(
                f"{cat}(样本 {base_stats['total']} < {min_tasks_for_category})"
            )
            continue

        checked_categories.append(cat)

        base = base_stats["pass_rate"]
        curr = curr_stats["pass_rate"]
        if curr < base - regression_threshold:
            passed = False
            messages.append(f"❌ [{cat}] 回归: {base:.1%} → {curr:.1%}")
        else:
            messages.append(f"✓ [{cat}]: {curr:.1%} (基线 {base:.1%})")

    # 附注跳过的类别，便于排查
    if skipped_categories:
        messages.append(f"· 跳过门禁的类别: {', '.join(skipped_categories)}")

    return passed, messages
