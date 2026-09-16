"""Day 27: 成本核算。

区分输入/输出/缓存命中，按模型定价计算。
仅统计 DeepSeek 与 Qwen 系列模型。
"""

from __future__ import annotations

from dataclasses import dataclass

from observability.metrics import MetricsCollector

# 默认模型：未匹配到定价时回退到此模型的费率
DEFAULT_MODEL = "qwen3.8-max-0902"


# 每百万 token 的价格（USD）
# 仅保留 DeepSeek 与 Qwen 系列
PRICING: dict[str, dict[str, float]] = {
    # ========== Qwen ==========
    "qwen3.8-max-0902": {
        "input": 1.60,
        "output": 6.40,
        "cache_read": 0.16,
        "cache_write": 2.00,
    },
    "qwen-max": {
        "input": 1.60,
        "output": 6.40,
        "cache_read": 0.16,
        "cache_write": 2.00,
    },
    "qwen-plus": {
        "input": 0.40,
        "output": 1.20,
        "cache_read": 0.04,
        "cache_write": 0.50,
    },
    "qwen-turbo": {
        "input": 0.05,
        "output": 0.20,
        "cache_read": 0.005,
        "cache_write": 0.06,
    },
    # ========== DeepSeek ==========
    "deepseek-chat": {
        "input": 0.27,
        "output": 1.10,
        "cache_read": 0.07,
        "cache_write": 0.27,
    },
    "deepseek-reasoner": {
        "input": 0.55,
        "output": 2.19,
        "cache_read": 0.14,
        "cache_write": 0.55,
    },
}


@dataclass
class CostBreakdown:
    """成本明细。"""

    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_read_cost: float = 0.0
    cache_write_cost: float = 0.0

    @property
    def total(self) -> float:
        return self.input_cost + self.output_cost + self.cache_read_cost + self.cache_write_cost

    def to_text(self) -> str:
        return (
            f"输入:    ${self.input_cost:.4f}\n"
            f"输出:    ${self.output_cost:.4f}\n"
            f"缓存读:  ${self.cache_read_cost:.4f}\n"
            f"缓存写:  ${self.cache_write_cost:.4f}\n"
            f"合计:    ${self.total:.4f}"
        )


class CostCalculator:
    """成本计算器。"""

    def __init__(self, pricing: dict[str, dict[str, float]] | None = None):
        self.pricing = pricing or PRICING

    def _lookup(self, model: str) -> dict[str, float]:
        """查找模型定价。

        匹配优先级：
        1. 精确匹配
        2. 前缀匹配（按 key 长度降序，避免 "qwen-max" 抢在
           "qwen3.8-max-0902" 前面匹配）
        3. 回退到 DEFAULT_MODEL
        """
        # 1. 精确匹配
        if model in self.pricing:
            return self.pricing[model]

        # 2. 前缀匹配：长 key 优先
        for key in sorted(self.pricing, key=len, reverse=True):
            if model.startswith(key):
                return self.pricing[key]

        # 3. 回退到默认模型
        return self.pricing[DEFAULT_MODEL]

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> CostBreakdown:
        """计算一次调用的成本。"""
        p = self._lookup(model)
        return CostBreakdown(
            input_cost=input_tokens * p["input"] / 1_000_000,
            output_cost=output_tokens * p["output"] / 1_000_000,
            cache_read_cost=cache_read_tokens * p["cache_read"] / 1_000_000,
            cache_write_cost=cache_write_tokens * p["cache_write"] / 1_000_000,
        )

    def from_metrics(self, metrics: MetricsCollector, model: str) -> CostBreakdown:
        """从 MetricsCollector 聚合成本。"""
        return self.calculate(
            model=model,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            cache_read_tokens=metrics.cache_read_tokens,
            cache_write_tokens=metrics.cache_write_tokens,
        )
