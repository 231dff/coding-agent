"""Day 17: 预算控制测试。"""

import pytest

from context.budget import BudgetConfig, ToolResultBudget


@pytest.fixture
def budget(tmp_path):
    return ToolResultBudget(tmp_path, BudgetConfig(token_threshold=100))


def test_small_result_passes_through(budget):
    result = budget.process_tool_result("call-1", "small output", "grep")
    assert result == "small output"


def test_large_result_offloaded(budget):
    big = "x" * 2000  # 约 500 tokens
    result = budget.process_tool_result("call-1", big, "grep")
    assert "已落盘" in result
    assert "call-1" not in result or "文件" in result


def test_frozen_decision(budget):
    big = "x" * 2000
    r1 = budget.process_tool_result("call-1", big, "grep")
    r2 = budget.process_tool_result("call-1", big, "grep")
    assert r1 == r2  # 第二次返回缓存的预览
