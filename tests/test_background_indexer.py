"""后台索引器测试。"""

import time

import pytest

from codebase.background_indexer import (
    BackgroundIndexer,
    IndexStatus,
)
from codebase.indexer import CodeIndexer
from codebase.parser import CodeParser


@pytest.fixture
def project(tmp_path):
    for i in range(20):
        (tmp_path / f"mod{i}.py").write_text(
            f"def func_{i}(x):\n    '''处理类型 {i} 的数据'''\n    return x + {i}\n"
        )
    return tmp_path


def test_immediate_return(tmp_path, project):
    """start() 立即返回，不阻塞。"""
    parser = CodeParser(project)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")

    bg = BackgroundIndexer(parser, indexer)
    t0 = time.time()
    bg.start(background=True)
    elapsed = time.time() - t0

    assert elapsed < 0.1, "start 应立返回"
    bg.wait(timeout=30)
    assert bg.is_ready()


def test_status_transitions(tmp_path, project):
    """状态机: PENDING → INDEXING → READY。"""
    parser = CodeParser(project)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")
    bg = BackgroundIndexer(parser, indexer)

    assert bg.status == IndexStatus.PENDING

    bg.start(background=True)
    # 启动后可能立即 READY（小项目），或短暂 INDEXING
    bg.wait(timeout=30)
    assert bg.status == IndexStatus.READY


def test_search_blocked_before_ready(tmp_path, project):
    """索引未就绪时 search 抛异常。"""
    parser = CodeParser(project)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")
    bg = BackgroundIndexer(parser, indexer)
    # 未启动
    with pytest.raises(RuntimeError, match="未就绪"):
        bg.search("test")


def test_progress_snapshot(tmp_path, project):
    """进度快照字段完整。"""
    parser = CodeParser(project)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")
    bg = BackgroundIndexer(parser, indexer)
    bg.start(background=True)
    bg.wait(timeout=30)

    snap = bg.snapshot()
    assert snap.total == 20
    assert snap.done == 20
    assert snap.chunks_indexed >= 20
    assert snap.started_at is not None
    assert snap.finished_at is not None
    assert snap.error is None


def test_graceful_stop(tmp_path, project):
    """优雅停止不抛异常。"""
    parser = CodeParser(project)
    indexer = CodeIndexer(parser, persist_dir=tmp_path / "idx")
    bg = BackgroundIndexer(parser, indexer)
    bg.start(background=True)
    bg.stop(timeout=5)


def test_failure_captured(tmp_path, project):
    """索引失败时状态置为 FAILED 且记录错误。"""
    parser = CodeParser(project)

    class BrokenIndexer(CodeIndexer):
        def index_files(self, *args, **kwargs):
            raise RuntimeError("模拟索引失败")

    indexer = BrokenIndexer(parser, persist_dir=tmp_path / "idx")
    bg = BackgroundIndexer(parser, indexer)
    bg.start(background=False)  # 同步执行便于断言
    bg.wait(timeout=5)

    assert bg.status == IndexStatus.FAILED
    assert "模拟索引失败" in bg.snapshot().error
