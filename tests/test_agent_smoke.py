"""Day 3: Agent 冒烟测试。3 个场景验证基础闭环。"""
import pytest
from agent.config import AgentConfig
from agent.core import build_agent


@pytest.fixture(scope="module")
def agent(tmp_path_factory):
    ws = tmp_path_factory.mktemp("agent_ws")
    (ws / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # BUG: should be +\n"
    )
    cfg = AgentConfig(workspace=str(ws), model="openai:gpt-5.5")
    return build_agent(cfg), ws


def _run(agent, ws, task: str):
    return agent.invoke(
        {"messages": [{"role": "user", "content": task}]},
        config={"configurable": {"thread_id": "smoke-test"}},
    )


def test_scenario_fix_bug(agent):
    """场景 1：修复明确的 Bug。"""
    a, ws = agent
    _run(a, ws, "calc.py 里 add 函数的返回值有 bug，请读取文件并修复。只修改这一处。")
    content = (ws / "calc.py").read_text()
    assert "return a + b" in content


def test_scenario_rename_function(agent):
    """场景 2：重命名函数。"""
    a, ws = agent
    (ws / "util.py").write_text("def old_name():\n    return 42\n")
    _run(a, ws, "把 util.py 里的 old_name 重命名为 new_name，只改这一个文件。")
    content = (ws / "util.py").read_text()
    assert "new_name" in content
    assert "old_name" not in content


def test_scenario_add_comment(agent):
    """场景 3：添加注释。"""
    a, ws = agent
    _run(a, ws, "给 calc.py 的 add 函数上方添加一行注释说明其用途，不要修改其他内容。")
    content = (ws / "calc.py").read_text()
    assert "#" in content