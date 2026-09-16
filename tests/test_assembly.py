"""Day 16: 上下文装配测试。"""
import pytest
from context.assembly import ContextAssembler
from langchain_core.messages import HumanMessage, AIMessage


def test_stable_prefix_unchanged():
    asm = ContextAssembler(
        system_prompt="You are a coder.",
        tool_definitions="read_file, write_file",
        project_memory="Use uv.",
    )
    # 多次装配，前缀哈希不变
    for _ in range(5):
        asm.assemble()
        assert asm.check_prefix_stability()


def test_prefix_change_detected():
    asm = ContextAssembler(system_prompt="v1")
    asm.assemble()
    asm.layers.system_prompt = "v2"  # 意外修改
    assert not asm.check_prefix_stability()


def test_message_order_is_stable():
    asm = ContextAssembler(system_prompt="sys")
    asm.update_summary("summary")
    asm.update_recent([HumanMessage(content="hello")])
    asm.update_current("file content")

    msgs = asm.assemble()
    # system → recent → current
    assert "sys" in str(msgs[0].content)
    assert "summary" in str(msgs[0].content)
    assert "hello" in str(msgs[1].content)
    assert "file content" in str(msgs[2].content)