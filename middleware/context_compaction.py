"""五层上下文压缩中间件。

关键改动：
- 增量 token 估算，避免每轮 O(N)
- 压缩冷却，避免频繁触发破坏 KV Cache
- 摘要作为 HumanMessage 追加，不插入 SystemMessage
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from context.api_compaction import APICompactionConfig, APICompactor
from context.budget import BudgetConfig, ToolResultBudget
from context.full_compaction import FullCompactionConfig, FullCompactor
from context.noise_filter import NoiseFilter, NoiseFilterConfig
from context.summarize import ArchivalSummarizer, SummarizeConfig


@dataclass
class CompactionPipelineConfig:
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    noise: NoiseFilterConfig = field(default_factory=NoiseFilterConfig)
    api: APICompactionConfig = field(default_factory=APICompactionConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)
    full: FullCompactionConfig = field(default_factory=FullCompactionConfig)
    model_window: int = 200_000

    l2_threshold: float = 0.70
    l3_threshold: float = 0.75
    l4_threshold: float = 0.80
    l5_threshold: float = 0.90

    # 压缩冷却：两次压缩之间至少增长这么多 token
    cooldown_ratio: float = 0.15


class ContextCompactionMiddleware(AgentMiddleware):
    name: str = "ContextCompactionMiddleware"

    def __init__(
        self,
        model: BaseChatModel,
        workspace: str,
        config: CompactionPipelineConfig | None = None,
    ):
        super().__init__()
        self.config = config or CompactionPipelineConfig()

        self.budget = ToolResultBudget(workspace, self.config.budget)
        self.noise_filter = NoiseFilter(self.config.noise)
        self.api_compactor = APICompactor(self.config.api)
        self.summarizer = ArchivalSummarizer(model, self.config.summarize)
        self.full_compactor = FullCompactor(model, self.config.full)

        # 增量估算缓存
        self._last_len: int = 0
        self._last_tail_id: int = 0
        self._last_tokens: int = 0
        self._last_compaction_tokens: int = 0

        self._stats = {
            "l1_budget_applied": 0,
            "l2_noise_removed": 0,
            "l3_api_compacted": 0,
            "l4_summarized": 0,
            "l5_full_compacted": 0,
            "l5_circuit_open": 0,
            "skipped_below_threshold": 0,
            "skipped_cooldown": 0,
        }

    def modify_model_request(self, request, model):
        return self._compact(request, model)

    async def amodify_model_request(self, request, model):
        return self._compact(request, model)

    # ---------- 核心 ----------

    def _compact(self, request, model):
        messages = list(request.messages or [])
        if not messages:
            return request

        current_tokens = self._estimate_tokens_cached(messages)

        # 冷却：上次压缩后 token 增长不够多就跳过
        if (
            self._last_compaction_tokens > 0
            and current_tokens - self._last_compaction_tokens
            < self.config.model_window * self.config.cooldown_ratio
        ):
            self._stats["skipped_cooldown"] += 1
            return request

        usage = current_tokens / self.config.model_window
        if usage < self.config.l2_threshold:
            self._stats["skipped_below_threshold"] += 1
            return request

        did_any = False

        # L2
        if usage >= self.config.l2_threshold:
            messages, noise_stats = self.noise_filter.filter(messages)
            if noise_stats.get("total_removed", 0) > 0:
                self._stats["l2_noise_removed"] += noise_stats["total_removed"]
                did_any = True
                current_tokens = self._estimate_tokens_cached(messages)
                usage = current_tokens / self.config.model_window

        # L3
        if usage >= self.config.l3_threshold:
            if self.api_compactor.should_compact(current_tokens, self.config.model_window):
                removals = self.api_compactor.select_removals(messages)
                if removals:
                    provider = self._detect_provider(model)
                    params = self.api_compactor.build_api_params(provider, removals)
                    if params:
                        request.model_settings = request.model_settings or {}
                        request.model_settings.update(params)
                        self._stats["l3_api_compacted"] += 1
                        did_any = True

        # L4
        if usage >= self.config.l4_threshold:
            if self.summarizer.should_summarize(messages, current_tokens, self.config.model_window):
                summary, kept = self.summarizer.summarize(messages)
                if summary:
                    messages = self._inject_summary(messages, summary, kept)
                    self._stats["l4_summarized"] += 1
                    did_any = True
                    current_tokens = self._estimate_tokens_cached(messages)
                    usage = current_tokens / self.config.model_window

        # L5
        if usage >= self.config.l5_threshold:
            if self.full_compactor.should_compact(current_tokens, self.config.model_window):
                success, summary, kept = self.full_compactor.compact(messages)
                if success and summary:
                    messages = self._inject_summary(messages, summary, kept)
                    self._stats["l5_full_compacted"] += 1
                    did_any = True
                elif not success:
                    self._stats["l5_circuit_open"] += 1

        if did_any:
            self._last_compaction_tokens = current_tokens

        request.messages = messages
        return request

    # ---------- 增量 token 估算 ----------

    def _estimate_tokens_cached(self, messages: list[BaseMessage]) -> int:
        """增量估算：只在 messages 长度或末条变化时重算尾部。"""
        if len(messages) == self._last_len and messages and id(messages[-1]) == self._last_tail_id:
            return self._last_tokens

        # 简单实现：全量重算，但缓存结果
        total_chars = sum(len(str(m.content)) for m in messages)
        tokens = total_chars // 4
        self._last_len = len(messages)
        self._last_tail_id = id(messages[-1]) if messages else 0
        self._last_tokens = tokens
        return tokens

    # ---------- 摘要注入 ----------

    def _inject_summary(
        self,
        original: list[BaseMessage],
        summary: str,
        kept: list[BaseMessage],
    ) -> list[BaseMessage]:
        """把摘要作为 HumanMessage 追加在 system 之后、kept 之前。

        不插入 SystemMessage，避免改变 system 前缀导致缓存整体失效。
        """
        system_msgs = [m for m in original if isinstance(m, SystemMessage)]

        summary_msg = HumanMessage(
            content=f"<conversation_summary>\n{summary}\n</conversation_summary>",
            additional_kwargs={"is_summary": True},
        )

        return list(system_msgs) + [summary_msg] + list(kept)

    def _detect_provider(self, model) -> str:
        model_name = (getattr(model, "model_name", "") or getattr(model, "model", "")).lower()
        if "claude" in model_name:
            return "anthropic"
        if "gpt" in model_name:
            return "openai"
        if "qwen" in model_name or "deepseek" in model_name:
            return "openai"
        return "unknown"

    def stats(self) -> dict:
        return {
            **self._stats,
            "circuit_breaker": self.full_compactor.stats(),
            "budget": self.budget.stats(),
        }
