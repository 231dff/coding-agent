"""Day 19: 摘要测试。"""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from context.summarize import ArchivalSummarizer, SummarizeConfig


@pytest.fixture
def summarizer():
    fake_model = FakeListChatModel(
        responses=[
            "## Round 1\n- **Intent**: Fix bug\n- **Actions**:\n  - read calc.py\n  - edit calc.py\n"
        ]
    )
    return ArchivalSummarizer(fake_model, SummarizeConfig(keep_recent=1))


def test_summarize_returns_summary_and_kept(summarizer):
    messages = [
        HumanMessage(content="fix bug"),
        AIMessage(content="ok"),
        HumanMessage(content="recent"),
    ]
    summary, kept = summarizer.summarize(messages)
    assert "Round 1" in summary
    assert len(kept) == 1
    assert kept[0].content == "recent"


def test_summary_preserves_structure(summarizer):
    messages = [
        HumanMessage(content="task"),  # 这条会被总结
        HumanMessage(content="recent"),  # 这条会被保留
    ]
    summary, _ = summarizer.summarize(messages)
    assert "Intent" in summary
    assert "Actions" in summary
