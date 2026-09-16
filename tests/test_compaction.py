"""Day 20: 压缩流水线测试。"""
import pytest
from context.full_compaction import FullCompactor, CircuitBreaker, CircuitState
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage


def test_circuit_breaker_opens_after_failures():
    cb = CircuitBreaker(threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.can_attempt()


def test_circuit_breaker_recovers():
    cb = CircuitBreaker(threshold=1, recovery_timeout=0.1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    import time
    time.sleep(0.15)
    assert cb.can_attempt()
    assert cb.state == CircuitState.HALF_OPEN


def test_full_compaction_success():
    model = FakeListChatModel(responses=["compressed summary"])
    compactor = FullCompactor(model)

    # 用多条、多样化的文本，确保触发压缩条件
    messages = [
        HumanMessage(content=f"这是第 {i} 条历史消息，包含一些需要归档的内容。")
        for i in range(10)
    ]

    success, summary, kept = compactor.compact(messages)
    assert success
    assert "compressed" in summary


def test_circuit_breaker_blocks_after_failures():
    class FailingModel:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("API error")

    compactor = FullCompactor(FailingModel())

    # 同样使用多条消息，确保 compact 会调用模型
    messages = [
        HumanMessage(content=f"这是第 {i} 条历史消息，包含一些需要归档的内容。")
        for i in range(10)
    ]

    # 连续失败 3 次
    for _ in range(3):
        compactor.compact(messages)

    assert compactor.circuit_breaker.state == CircuitState.OPEN

    # 后续调用被阻止
    success, _, _ = compactor.compact(messages)
    assert not success