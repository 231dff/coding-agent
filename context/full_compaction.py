"""Day 20: 全量压缩 (L5) + 熔断器。

LLM 驱动的完整压缩，作为最后手段。
配备连续失败的熔断器，避免在压缩失败的会话上持续烧钱。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage


class CircuitState(str, Enum):
    CLOSED = "closed"  # 正常
    OPEN = "open"  # 熔断中
    HALF_OPEN = "half_open"  # 半开（探测恢复）


@dataclass
class FullCompactionConfig:
    """全量压缩配置。"""

    # 触发阈值
    trigger_fraction: float = 0.95
    # 目标压缩比例
    target_fraction: float = 0.50
    # 保留最后 N 条原文
    keep_recent: int = 3
    # 熔断器：连续失败次数
    circuit_breaker_threshold: int = 3
    # 熔断器：恢复等待时间（秒）
    circuit_recovery_timeout: float = 300.0
    # 压缩 prompt 模板
    prompt_template: str = ""


DEFAULT_COMPACTION_PROMPT = """你是一个上下文压缩器。请将以下对话历史压缩为一个紧凑的摘要。

保留：
1. 任务目标和当前进度
2. 关键的架构决策和理由
3. 已修改的文件和接口
4. 失败路径和踩坑记录
5. 未完成的工作

丢弃：
1. 重复的搜索结果
2. 已被替代的旧代码片段
3. 无关的闲聊

输出格式：一个结构化的 markdown 摘要，不超过 {target_tokens} token。

对话历史：
{messages}
"""


class CircuitBreaker:
    """熔断器。

    连续失败 N 次后打开，阻止后续压缩尝试，
    避免在无法压缩的会话上持续消耗 token。
    """

    def __init__(
        self,
        threshold: int = 3,
        recovery_timeout: float = 300.0,
    ):
        self.threshold = threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None

    def can_attempt(self) -> bool:
        """判断是否允许尝试压缩。"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            # 检查是否超过恢复时间
            if (
                self.last_failure_time
                and (time.time() - self.last_failure_time) >= self.recovery_timeout
            ):
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False

    def record_success(self) -> None:
        """记录成功。"""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None

    def record_failure(self) -> None:
        """记录失败。"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.state = CircuitState.OPEN


class FullCompactor:
    """全量压缩器 (L5)。"""

    def __init__(
        self,
        model: BaseChatModel,
        config: FullCompactionConfig | None = None,
    ):
        self.model = model
        self.config = config or FullCompactionConfig()
        self.circuit_breaker = CircuitBreaker(
            threshold=self.config.circuit_breaker_threshold,
            recovery_timeout=self.config.circuit_recovery_timeout,
        )
        self._prompt = self.config.prompt_template or DEFAULT_COMPACTION_PROMPT

    def should_compact(self, current_tokens: int, model_window: int) -> bool:
        """判断是否需要全量压缩。"""
        if not self.circuit_breaker.can_attempt():
            return False
        return (current_tokens / model_window) >= self.config.trigger_fraction

    def compact(self, messages: list[BaseMessage]) -> tuple[bool, str, list[BaseMessage]]:
        """执行全量压缩。

        Returns:
            (success, summary, kept_messages)
        """
        if not self.circuit_breaker.can_attempt():
            return False, "", messages

        # 保留最近消息
        cutoff = max(0, len(messages) - self.config.keep_recent)
        to_compact = messages[:cutoff]
        kept = messages[cutoff:]

        if not to_compact:
            return True, "", kept

        # 估算目标 token
        original_chars = sum(len(str(m.content)) for m in to_compact)
        target_chars = int(original_chars * self.config.target_fraction)
        target_tokens = target_chars // 4

        # 构建 prompt
        messages_text = self._format_messages(to_compact)
        prompt = self._prompt.format(
            target_tokens=target_tokens,
            messages=messages_text,
        )

        try:
            response = self.model.invoke([HumanMessage(content=prompt)])
            summary = (
                response.content if isinstance(response.content, str) else str(response.content)
            )

            # 验证压缩结果
            if not summary or len(summary) < 10:
                raise ValueError("压缩结果为空或过短")

            self.circuit_breaker.record_success()
            return True, summary, kept

        except Exception as e:
            self.circuit_breaker.record_failure()
            return False, f"压缩失败: {e}", messages

    def _format_messages(self, messages: list[BaseMessage]) -> str:
        """格式化消息。"""
        lines = []
        for msg in messages:
            role = msg.__class__.__name__.replace("Message", "")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 3000:
                content = content[:3000] + "..."
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def stats(self) -> dict:
        """返回熔断器状态。"""
        return {
            "circuit_state": self.circuit_breaker.state.value,
            "failure_count": self.circuit_breaker.failure_count,
            "threshold": self.config.circuit_breaker_threshold,
        }
