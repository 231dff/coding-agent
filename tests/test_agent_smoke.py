"""Day 3: Agent 冒烟测试。3 个场景验证基础闭环。

这些测试需要真实 LLM 调用。国内环境访问 OpenAI 会被 403 拒绝。
默认 skip，通过环境变量启用：

    # 用 OpenAI 兼容端点（qwen / moonshot / deepseek）
    set AGENT_SMOKE_MODEL=qwen:qwen-max
    set AGENT_SMOKE_REAL=1
    pytest tests/test_agent_smoke.py -v

    # 或用 OpenAI（需可访问区域）
    set AGENT_SMOKE_REAL=1
    pytest tests/test_agent_smoke.py -v
"""

import os

import pytest

from agent.config import AgentConfig
from agent.core import build_agent

# 只有显式开启时才跑
_SMOKE_ENABLED = os.getenv("AGENT_SMOKE_REAL", "").lower() in ("1", "true", "yes")
_SMOKE_MODEL = os.getenv("AGENT_SMOKE_MODEL", "openai:gpt-4o")

pytestmark = pytest.mark.skipif(
    not _SMOKE_ENABLED,
    reason=(
        "冒烟测试需要真实 LLM。设置 AGENT_SMOKE_REAL=1 启用；"
        "用 AGENT_SMOKE_MODEL 指定模型（如 qwen:qwen-max）。"
    ),
)


@pytest.fixture(scope="module")
def agent(tmp_path_factory):
    ws = tmp_path_factory.mktemp("agent_ws")
    (ws / "calc.py").write_text(
    "def add(a, b):\n    return a - b  # BUG: should be +\n",
    encoding="utf-8",
)
    cfg = AgentConfig.for_test(workspace=str(ws), model=_SMOKE_MODEL)
    rt = build_agent(cfg)
    yield rt, ws
    rt.close()


def _run(rt, ws, task: str):
    return rt.invoke(
        {"messages": [{"role": "user", "content": task}]},
        config={"configurable": {"thread_id": "smoke-test"}},
    )


def test_scenario_fix_bug(agent):
    """场景 1：修复明确的 Bug。"""
    rt, ws = agent
    _run(rt, ws, "calc.py 里 add 函数的返回值有 bug，请读取文件并修复。只修改这一处。")
    content = (ws / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in content


def test_scenario_rename_function(agent):
    """场景 2：重命名函数。"""
    rt, ws = agent
    (ws / "util.py").write_text(
    "def old_name():\n    return 42\n",
    encoding="utf-8",
)
    _run(rt, ws, "把 util.py 里的 old_name 重命名为 new_name，只改这一个文件。")
    content = (ws / "util.py").read_text(encoding="utf-8")
    assert "new_name" in content
    assert "old_name" not in content


def test_scenario_add_comment(agent):
    """场景 3：添加注释。"""
    rt, ws = agent
    _run(rt, ws, "给 calc.py 的 add 函数上方添加一行注释说明其用途，不要修改其他内容。")
    content = (ws / "calc.py").read_text(encoding="utf-8")
    assert "#" in content
