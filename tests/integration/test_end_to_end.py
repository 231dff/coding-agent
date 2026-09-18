"""端到端集成测试。

默认 skip（需要真实 LLM）。通过环境变量启用：

    $env:AGENT_SMOKE_REAL = "1"
    $env:AGENT_SMOKE_MODEL = "qwen:qwen-max"
    pytest tests/integration/ -v
"""

from __future__ import annotations

import os

import pytest

_SMOKE_ENABLED = os.getenv("AGENT_SMOKE_REAL", "").lower() in ("1", "true", "yes")
_SMOKE_MODEL = os.getenv("AGENT_SMOKE_MODEL", "openai:gpt-4o")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _SMOKE_ENABLED,
        reason="需要真实 LLM。设置 AGENT_SMOKE_REAL=1 启用。",
    ),
]


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    """构建一个 AgentRuntime，用于测试。"""
    from agent.config import AgentConfig
    from agent.core import build_agent

    ws = tmp_path_factory.mktemp("e2e_ws")
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")

    cfg = AgentConfig.for_test(workspace=str(ws), model=_SMOKE_MODEL)
    rt = build_agent(cfg)
    yield rt, ws
    rt.close()


def test_read_file(runtime):
    """读文件任务：应找到 README 或返回文件内容。"""
    rt, ws = runtime
    result = rt.invoke(
        {"messages": [{"role": "user", "content": "读一下 calc.py"}]},
        config={"configurable": {"thread_id": "e2e-read"}},
    )
    assert result["messages"]
    # 最后一条消息应包含内容
    last = result["messages"][-1]
    assert last.content or last.tool_calls


def test_fix_bug(runtime):
    """修 bug 任务：应把 `a - b` 改成 `a + b`。"""
    rt, ws = runtime
    rt.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "calc.py 里 add 函数的返回值有 bug，修复它。",
                }
            ]
        },
        config={"configurable": {"thread_id": "e2e-fix"}},
    )
    content = (ws / "calc.py").read_text()
    assert "a + b" in content
