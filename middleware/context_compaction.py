"""五层上下文压缩中间件。

缓存友好设计：
- 每层都有明确的触发阈值，不轻易触发
- 压缩不修改 system 消息，摘要作为独立消息追加
- 同步 + 异步双实现
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage

from context.budget import ToolResultBudget, BudgetConfig
from context.noise_filter import NoiseFilter, NoiseFilterConfig
from context.api_compaction import APICompactor, APICompactionConfig
from context.summarize import ArchivalSummarizer, SummarizeConfig
from context.full_compaction import FullCompactor, FullCompactionConfig


@dataclass
class CompactionPipelineConfig:
    """压缩流水线配置。

    **缓存友好默认值**：每层的触发阈值都设在合理位置。
    - L2（噪声删除）只在 70% 时触发
    - L3（API 微压缩）只在 75% 时触发
    - L4（归档摘要）只在 80% 时触发
    - L5（全量压缩）只在 90% 时触发
    """
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    noise: NoiseFilterConfig = field(default_factory=NoiseFilterConfig)
    api: APICompactionConfig = field(default_factory=APICompactionConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)
    full: FullCompactionConfig = field(default_factory=FullCompactionConfig)
    model_window: int = 200_000

    # 各层触发阈值（相对 model_window 的比例）
    l2_threshold: float = 0.70
    l3_threshold: float = 0.75
    l4_threshold: float = 0.80
    l5_threshold: float = 0.90


class ContextCompactionMiddleware(AgentMiddleware):
    """五层上下文压缩中间件。"""

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

        self._stats = {
            "l1_budget_applied": 0,
            "l2_noise_removed": 0,
            "l3_api_compacted": 0,
            "l4_summarized": 0,
            "l5_full_compacted": 0,
            "l5_circuit_open": 0,
            "skipped_below_threshold": 0,
        }

    # ---------- 同步 ----------

    def modify_model_request(self, request, model):
        return self._compact(request, model)

    # ---------- 异步 ----------

    async def amodify_model_request(self, request, model):
        return self._compact(request, model)

    # ---------- 核心逻辑 ----------

    def _compact(self, request, model):
        messages = list(request.messages or [])
        current_tokens = self._estimate_tokens(messages)
        usage = current_tokens / self.config.model_window

        did_any_compaction = False

        # ---------- L2: 噪声删除（≥70%）----------
        if usage >= self.config.l2_threshold:
            messages, noise_stats = self.noise_filter.filter(messages)
            if noise_stats["total_removed"] > 0:
                self._stats["l2_noise_removed"] += noise_stats["total_removed"]
                did_any_compaction = True
            current_tokens = self._estimate_tokens(messages)
            usage = current_tokens / self.config.model_window

        # ---------- L3: API 微压缩（≥75%）----------
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
                        did_any_compaction = True

        # ---------- L4: 归档摘要（≥80%）----------
        if usage >= self.config.l4_threshold:
            if self.summarizer.should_summarize(
                messages, current_tokens, self.config.model_window
            ):
                summary, kept = self.summarizer.summarize(messages)
                if summary:
                    messages = self._inject_summary(messages, summary, kept)
                    self._stats["l4_summarized"] += 1
                    did_any_compaction = True
                    current_tokens = self._estimate_tokens(messages)
                    usage = current_tokens / self.config.model_window

        # ---------- L5: 全量压缩（≥90%）----------
        if usage >= self.config.l5_threshold:
            if self.full_compactor.should_compact(
                current_tokens, self.config.model_window
            ):
                success, summary, kept = self.full_compactor.compact(messages)
                if success and summary:
                    messages = self._inject_summary(messages, summary, kept)
                    self._stats["l5_full_compacted"] += 1
                    did_any_compaction = True
                elif not success:
                    self._stats["l5_circuit_open"] += 1

        if not did_any_compaction:
            self._stats["skipped_below_threshold"] += 1

        request.messages = messages
        return request

    def _inject_summary(
        self,
        original: list[BaseMessage],
        summary: str,
        kept: list[BaseMessage],
    ) -> list[BaseMessage]:
        """把摘要作为**独立消息**追加在 system 之后。

        **缓存友好**：不修改原 system 消息，避免整体缓存失效。
        """
        system_msgs = [m for m in original if isinstance(m, SystemMessage)]
        non_system_msgs = [m for m in original if not isinstance(m, SystemMessage)]

        result: list[BaseMessage] = []

        # 原 system 消息保持不动（缓存前缀的核心部分）
        result.extend(system_msgs)

        # 摘要作为独立 system-role 消息追加
        if summary:
            result.append(SystemMessage(
                content=f"## 对话摘要\n{summary}",
                additional_kwargs={"is_summary": True},
            ))

        # 保留最近消息（kept）
        result.extend(kept)

        return result

    def _estimate_tokens(self, messages: list[BaseMessage]) -> int:
        total_chars = sum(len(str(m.content)) for m in messages)
        return total_chars // 4

    def _detect_provider(self, model) -> str:
        model_name = getattr(model, "model_name", "") or getattr(model, "model", "")
        name_lower = model_name.lower()
        if "claude" in name_lower:
            return "anthropic"
        if "gpt" in name_lower:
            return "openai"
        # Qwen / DeepSeek 走 OpenAI 兼容协议
        if "qwen" in name_lower or "deepseek" in name_lower:
            return "openai"
        return "unknown"

    def stats(self) -> dict:
        return {
            **self._stats,
            "circuit_breaker": self.full_compactor.stats(),
            "budget": self.budget.stats(),
        }