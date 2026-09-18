"""SSE 事件契约测试。

防止 /api/chat/stream 的事件格式漂移。
"""

from __future__ import annotations

import json


def test_sse_format():
    """SSE 事件必须是 `event: X\\ndata: Y\\n\\n`。"""
    from api.mock import sse

    raw = sse("token", {"content": "hi"})
    lines = raw.strip().split("\n")

    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")

    event_type = lines[0][len("event: ") :]
    payload = json.loads(lines[1][len("data: ") :])

    assert event_type == "token"
    assert payload == {"content": "hi"}


def test_sse_payload_is_valid_json():
    """payload 必须是合法 JSON。"""
    from api.mock import sse

    raw = sse(
        "metrics",
        {
            "model": "qwen-max",
            "input_tokens": 100,
            "duration_s": 1.5,
        },
    )
    data_line = raw.split("\n")[1]
    payload = json.loads(data_line[len("data: ") :])

    assert payload["model"] == "qwen-max"
    assert payload["input_tokens"] == 100


def test_sse_done_event_has_session_id():
    """done 事件必须带 session_id。"""
    from api.mock import sse

    raw = sse("done", {"session_id": "abc123"})
    data_line = raw.split("\n")[1]
    payload = json.loads(data_line[len("data: ") :])

    assert "session_id" in payload
