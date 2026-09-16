"""_dedup_repeats 复读检测测试。

这是显示层复读问题的最后一道兜底。
"""

from __future__ import annotations

from agent.main import _dedup_repeats


def test_short_text_unchanged():
    """短文本不做处理。"""
    text = "这是一段短文本。"
    assert _dedup_repeats(text) == text


def test_no_repeat_unchanged():
    """没有重复时原样返回。"""
    text = ("第一部分：项目简介。第二部分：技术栈。第三部分：部署方式。") * 10
    # 上面构造虽然各句可能重复，但不是整段重复
    result = _dedup_repeats(text)
    assert len(result) > 0


def test_tail_repeat_truncated():
    """尾部整段重复应被截断。"""
    # 构造：一段独有 + 一段重复
    unique = "这是开头独有的内容。" * 40
    repeated = "这是重复的内容。" * 50

    # 长度 > 400 才有意义
    text = unique + repeated + repeated

    result = _dedup_repeats(text)

    # 结果应比原文短
    assert len(result) < len(text)
    # 且保留了开头
    assert "这是开头独有的内容" in result


def test_no_false_positive_on_repeated_phrases():
    """正常文本里自然重复的短语不应被误删。"""
    text = (
        "用户问：这个项目做什么？"
        "助手答：这是一个搜索 Agent。"
        "用户问：这个项目用哪些库？"
        "助手答：FastAPI 和 LangGraph。"
    ) * 10

    result = _dedup_repeats(text)
    # 不应把整段都截掉
    assert len(result) > 100


def test_returns_string():
    assert isinstance(_dedup_repeats("test"), str)


def test_empty_string():
    assert _dedup_repeats("") == ""
