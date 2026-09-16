"""归档式摘要 (L4) —— 任务感知版本。

核心改进（书中 2.7 / 实验 2-9）：
- 从"任务无关"的通用摘要改为"任务感知"摘要
- 压缩率从 ~30% 提升到 ~77%
- 迭代次数减少，成功率提升
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


@dataclass
class SummaryEntry:
    """一条归档摘要记录。"""
    round_number: int
    timestamp: float
    intent: str
    actions: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class SummarizeConfig:
    """摘要配置。"""
    every_n_rounds: int = 5
    trigger_fraction: float = 0.85
    keep_recent: int = 3
    max_summary_tokens: int = 1000
    # 是否启用任务感知压缩（新增）
    task_aware: bool = True


# 任务感知摘要提示（书中 2.7.5 的保留优先级）
TASK_AWARE_PROMPT = """你是上下文压缩器。压缩目标是**服务于当前任务**。

## 当前任务
{current_task}

## 当前已积累的上下文
{context}

## 压缩原则（按优先级）
1. **架构决策和关键约束**：不得摘要，完整保留
2. **已修改的文件列表和变更记录**：完整保留
3. **失败路径与原因**：完整保留（避免重复踩坑）
4. **未解决的 TODO**：完整保留
5. **与当前任务相关的搜索结果**：保留要点
6. **重复内容、与任务无关的搜索**：可删除
7. **所有标识符（UUID/hash/IP/URL/文件名/commit hash）**：原样保留

## 待压缩内容
{messages}

## 输出格式（严格遵守）
## Round {round_number}
- **Intent**: 本轮核心意图（一句话）
- **Actions**: 执行的关键动作（最多 5 条）
- **Decisions**: 架构/技术决策（每条一行）
- **Artifacts**: 产出的文件或变更
- **Failures**: 失败尝试及原因
- **Next**: 下一步计划

总长度控制在 {max_tokens} token 以内。
"""


class ArchivalSummarizer:
    """归档式摘要器（任务感知版）。"""

    def __init__(
        self,
        model: BaseChatModel,
        config: SummarizeConfig | None = None,
    ):
        self.model = model
        self.config = config or SummarizeConfig()
        self.entries: list[SummaryEntry] = []
        self._round = 0
        self._current_task = ""

    def set_current_task(self, task: str) -> None:
        """设置当前任务描述（由中间件从 state 中提取）。"""
        self._current_task = task

    def should_summarize(
        self,
        messages: list[BaseMessage],
        current_tokens: int,
        model_window: int,
    ) -> bool:
        if self._round > 0 and self._round % self.config.every_n_rounds == 0:
            return True
        if (current_tokens / model_window) >= self.config.trigger_fraction:
            return True
        return False

    def summarize(
        self,
        messages: list[BaseMessage],
    ) -> tuple[str, list[BaseMessage]]:
        """执行摘要。返回 (summary_text, kept_messages)。"""
        self._round += 1

        cutoff = max(0, len(messages) - self.config.keep_recent)
        to_summarize = messages[:cutoff]
        kept = messages[cutoff:]

        if not to_summarize:
            return "", kept

        messages_text = self._format_messages(to_summarize)

        # 构建压缩提示
        if self.config.task_aware and self._current_task:
            prompt = TASK_AWARE_PROMPT.format(
                current_task=self._current_task,
                context=self._build_summary_text() or "(无)",
                round_number=self._round,
                max_tokens=self.config.max_summary_tokens,
                messages=messages_text,
            )
        else:
            prompt = self._generic_prompt(messages_text)

        response = self.model.invoke([HumanMessage(content=prompt)])
        summary = response.content if isinstance(response.content, str) else str(response.content)

        entry = self._parse_summary(summary)
        if entry:
            self.entries.append(entry)

        return self._build_summary_text(), kept

    def _generic_prompt(self, messages_text: str) -> str:
        """降级：任务无关的通用摘要。"""
        return f"""你是一个对话摘要器。请将以下对话压缩为结构化摘要。

输出格式：
## Round {self._round}
- **Intent**: 本轮核心意图
- **Actions**: 关键动作
- **Decisions**: 决策
- **Artifacts**: 产出
- **Failures**: 失败路径
- **Next**: 下一步

对话：
{messages_text}
"""

    def _format_messages(self, messages: list[BaseMessage]) -> str:
        lines = []
        for msg in messages:
            role = msg.__class__.__name__.replace("Message", "")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 2000:
                content = content[:2000] + "..."
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _parse_summary(self, summary: str) -> SummaryEntry | None:
        entry = SummaryEntry(
            round_number=self._round,
            timestamp=time.time(),
            intent="",
        )
        current_key = None
        for line in summary.splitlines():
            stripped = line.strip()
            if stripped.startswith("- **Intent**:"):
                entry.intent = stripped.replace("- **Intent**:", "").strip()
            elif stripped.startswith("- **Actions**:"):
                current_key = "actions"
            elif stripped.startswith("- **Decisions**:"):
                current_key = "decisions"
            elif stripped.startswith("- **Artifacts**:"):
                current_key = "artifacts"
            elif stripped.startswith("- **Failures**:"):
                current_key = "failures"
            elif stripped.startswith("- **Next**:"):
                current_key = "next_steps"
            elif stripped.startswith("- ") and current_key:
                getattr(entry, current_key).append(stripped[2:].strip())
        return entry

    def _build_summary_text(self) -> str:
        parts = []
        for entry in self.entries:
            parts.append(f"## Round {entry.round_number}")
            if entry.intent:
                parts.append(f"- **Intent**: {entry.intent}")
            for key, label in [
                ("actions", "Actions"),
                ("decisions", "Decisions"),
                ("artifacts", "Artifacts"),
                ("failures", "Failures"),
                ("next_steps", "Next"),
            ]:
                items = getattr(entry, key)
                if items:
                    parts.append(f"- **{label}**:")
                    parts.extend(f"  - {i}" for i in items)
            parts.append("")
        return "\n".join(parts)