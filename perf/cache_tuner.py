"""Day 29: 缓存命中率调优。

分析前缀稳定性，识别导致缓存失效的变更。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from observability.metrics import MetricsCollector


@dataclass
class CacheAnalysis:
    """缓存分析结果。"""

    total_calls: int
    cache_hit_rate: float
    total_input_tokens: int
    total_cached_tokens: int
    savings_usd: float
    recommendations: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "缓存分析",
            "=" * 60,
            f"总调用次数: {self.total_calls}",
            f"缓存命中率: {self.cache_hit_rate:.1%}",
            f"输入 token: {self.total_input_tokens}",
            f"缓存读 token: {self.total_cached_tokens}",
            f"节省成本: ${self.savings_usd:.4f}",
            "",
        ]
        if self.recommendations:
            lines.append("优化建议:")
            for r in self.recommendations:
                lines.append(f"  - {r}")
        return "\n".join(lines)


class CacheTuner:
    """缓存命中率调优器。"""

    def __init__(self, metrics: MetricsCollector, model_pricing: dict | None = None):
        self.metrics = metrics
        self.pricing = model_pricing or {
            "input": 2.50,
            "cache_read": 0.25,
        }

    def analyze(self) -> CacheAnalysis:
        """分析当前缓存使用。"""
        hit_rate = self.metrics.cache_hit_rate()
        cached = self.metrics.cache_read_tokens
        total_input = self.metrics.input_tokens

        # 节省的成本 = 缓存读 token * (输入价 - 缓存读价)
        savings = cached * (self.pricing["input"] - self.pricing["cache_read"]) / 1_000_000

        recommendations = []
        if hit_rate < 0.5:
            recommendations.append("缓存命中率低于 50%。检查系统提示或工具定义是否在每轮变化。")
        if hit_rate < 0.2:
            recommendations.append(
                "缓存命中率极低。可能原因："
                "1) 每轮动态生成时间戳/随机数注入系统提示；"
                "2) 工具定义顺序不稳定；"
                "3) 未配置 cache_control / prompt_cache_key。"
            )
        if total_input > 0 and cached == 0:
            recommendations.append(
                "完全没有缓存命中。检查 PromptCacheMiddleware 是否生效，"
                "以及 provider 是否支持缓存。"
            )

        return CacheAnalysis(
            total_calls=self.metrics.llm_calls,
            cache_hit_rate=hit_rate,
            total_input_tokens=total_input,
            total_cached_tokens=cached,
            savings_usd=savings,
            recommendations=recommendations,
        )


def hash_prefix(system_prompt: str, tool_defs: str) -> str:
    """计算前缀哈希。用于在每轮请求前校验前缀是否稳定。"""
    combined = f"{system_prompt}\n---\n{tool_defs}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
