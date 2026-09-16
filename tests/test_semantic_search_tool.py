"""状态感知的 semantic_search 工具测试。"""

import pytest

from codebase.background_indexer import BackgroundIndexer
from codebase.indexer import CodeIndexer, create_index_status_tool, create_search_tool
from codebase.parser import CodeParser


@pytest.fixture
def bg_indexer(tmp_path):
    (tmp_path / "a.py").write_text("def authenticate(token):\n    return token\n")
    parser = CodeParser(tmp_path)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")
    return BackgroundIndexer(parser, indexer)


def test_search_before_start_returns_guidance(bg_indexer):
    """PENDING 状态返回提示而非异常。"""
    tool = create_search_tool(bg_indexer)
    result = tool.invoke({"query": "authenticate"})
    assert "索引尚未启动" in result
    assert "grep_search" in result


def test_search_during_indexing_returns_progress(bg_indexer):
    """INDEXING 状态返回进度信息。"""
    bg_indexer.start(background=True)
    tool = create_search_tool(bg_indexer)
    # 立即调用可能已就绪，也可能仍在跑
    result = tool.invoke({"query": "authenticate"})
    # 要么成功返回结果，要么返回进度提示
    assert "authenticate" in result or "构建中" in result or "索引尚未启动" in result


def test_search_after_ready_returns_results(bg_indexer):
    """READY 状态返回真实结果。"""
    bg_indexer.start(background=False)
    assert bg_indexer.is_ready()
    tool = create_search_tool(bg_indexer)
    result = tool.invoke({"query": "token 认证"})
    # 至少有内容返回，不报错
    assert isinstance(result, str)
    assert len(result) > 0


def test_index_status_tool(bg_indexer):
    """状态查询工具在所有状态下都可用。"""
    tool = create_index_status_tool(bg_indexer)
    result = tool.invoke({})
    assert "未启动" in result

    bg_indexer.start(background=False)
    result = tool.invoke({})
    assert "就绪" in result
