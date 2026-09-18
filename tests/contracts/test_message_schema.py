"""消息结构契约测试。

防止 LangChain 消息 schema 漂移。如果 LangChain 升级
导致消息字段变化，这里会先发现。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# ============================================================
# SystemMessage
# ============================================================


def test_system_message_has_content():
    msg = SystemMessage(content="you are helpful")
    assert msg.content == "you are helpful"
    assert msg.type == "system"


# ============================================================
# HumanMessage
# ============================================================


def test_human_message_has_content():
    msg = HumanMessage(content="hello")
    assert msg.content == "hello"
    assert msg.type == "human"


# ============================================================
# AIMessage
# ============================================================


def test_ai_message_with_content():
    msg = AIMessage(content="hi")
    assert msg.content == "hi"
    assert msg.type == "ai"


def test_ai_message_with_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"path": "README.md"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    assert msg.tool_calls
    assert msg.tool_calls[0]["name"] == "read_file"
    assert msg.tool_calls[0]["args"] == {"path": "README.md"}
    assert msg.tool_calls[0]["id"] == "call-1"


def test_ai_message_content_can_be_empty_with_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "grep_search",
                "args": {"pattern": "def "},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )
    assert msg.content == ""
    assert len(msg.tool_calls) == 1


# ============================================================
# AIMessageChunk（流式）
# ============================================================


def test_ai_message_chunk_has_content():
    chunk = AIMessageChunk(content="he")
    assert chunk.content == "he"


def test_ai_message_chunk_has_tool_call_chunks():
    """流式早期，tool_calls 为空，但 tool_call_chunks 有内容。"""
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": "read_file",
                "args": '{"path"',
                "id": "c1",
                "index": 0,
            }
        ],
    )
    assert chunk.tool_call_chunks
    assert chunk.tool_call_chunks[0]["name"] == "read_file"


# ============================================================
# ToolMessage
# ============================================================


def test_tool_message_has_tool_call_id():
    msg = ToolMessage(
        content="file content",
        tool_call_id="call-1",
    )
    assert msg.content == "file content"
    assert msg.tool_call_id == "call-1"
    assert msg.type == "tool"


def test_tool_message_with_name():
    msg = ToolMessage(
        content="ok",
        tool_call_id="c1",
        name="read_file",
    )
    assert msg.name == "read_file"


# ============================================================
# 序列化往返
# ============================================================


@pytest.mark.parametrize(
    "msg",
    [
        SystemMessage(content="sys"),
        HumanMessage(content="user"),
        AIMessage(content="ai"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "a.py"},
                    "id": "c1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="result", tool_call_id="c1"),
    ],
)
def test_message_roundtrip(msg):
    """消息可以 dict 化再复原。"""
    d = msg.model_dump()
    assert d["type"] == msg.type
    assert "content" in d
