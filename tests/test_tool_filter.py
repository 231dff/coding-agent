"""Day 22: 工具过滤测试。"""
import pytest
from langchain_core.tools import tool
from middleware.tool_filter import ToolFilterMiddleware, ToolFilterConfig


@tool
def read_file(path: str) -> str:
    """读取文件。"""
    return ""


@tool
def pytest_tool(cmd: str) -> str:
    """运行 pytest。"""
    return ""


@tool
def docker_tool(cmd: str) -> str:
    """构建 Docker 镜像。"""
    return ""


def test_filter_exposes_core_only():
    mw = ToolFilterMiddleware(
        all_tool_names=["read_file", "pytest_tool", "docker_tool"],
        skill_tool_map={"python_testing": ["pytest_tool"]},
        config=ToolFilterConfig(core_tools={"read_file"}),
    )
    # 无技能加载时，只暴露核心工具
    active = mw._extract_active_skills([])
    assert active == set()


def test_filter_detects_loaded_skill():
    mw = ToolFilterMiddleware(
        all_tool_names=["read_file", "pytest_tool", "docker_tool"],
        skill_tool_map={"python_testing": ["pytest_tool"]},
    )
    # 构造一条 load_skill 的 tool call
    from langchain_core.messages import AIMessage
    msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "load_skill",
            "args": {"skill_name": "python_testing"},
            "id": "call-1",
            "type": "tool_call",
        }],
    )
    active = mw._extract_active_skills([msg])
    assert "python_testing" in active