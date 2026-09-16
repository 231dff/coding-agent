"""Day 13: 事务测试。"""
import pytest
from pathlib import Path
from sandbox.base import Sandbox, ExecResult
from sandbox.transaction import EditTransaction, edit_transaction


class FakeSandbox(Sandbox):
    """测试用的假沙箱，直接操作本地文件。"""
    def start(self): pass
    def stop(self): pass
    def exec(self, command, timeout=60, cwd=None, env=None):
        return ExecResult(0, "", "", 0.0)
    def read_file(self, path): return ""
    def write_file(self, path, content): pass
    def upload_dir(self, local, remote): pass
    def download_dir(self, remote, local): pass


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("from a import foo\nprint(foo())\n")
    return tmp_path


def test_transaction_commit(ws):
    sandbox = FakeSandbox()
    tx = EditTransaction(sandbox, ws)
    tx.begin()

    ok, _ = tx.edit_file("a.py", "return 1", "return 2")
    assert ok
    ok, _ = tx.edit_file("b.py", "foo()", "foo()  # updated")
    assert ok

    result = tx.commit()
    assert result.ok
    assert "return 2" in (ws / "a.py").read_text()
    assert "# updated" in (ws / "b.py").read_text()


def test_transaction_rollback(ws):
    sandbox = FakeSandbox()
    tx = EditTransaction(sandbox, ws)
    tx.begin()
    tx.edit_file("a.py", "return 1", "return 999")
    tx.rollback()
    # 原文件未变
    assert "return 1" in (ws / "a.py").read_text()


def test_transaction_syntax_check_blocks(ws):
    sandbox = FakeSandbox()
    tx = EditTransaction(sandbox, ws)
    tx.begin()
    # 引入语法错误
    tx.edit_file("a.py", "def foo():\n    return 1\n", "def foo(:\n    return 1\n")
    result = tx.commit()
    assert not result.ok
    assert result.rolled_back
    # 原文件未变
    assert "def foo():" in (ws / "a.py").read_text()


def test_transaction_atomic_all_or_nothing(ws):
    sandbox = FakeSandbox()
    tx = EditTransaction(sandbox, ws)
    tx.begin()
    tx.edit_file("a.py", "return 1", "return 2")
    # 第二个编辑无效（找不到匹配），但不影响第一个的提交
    ok, msg = tx.edit_file("b.py", "nonexistent", "X")
    assert not ok
    result = tx.commit()
    assert result.ok
    assert len(result.edited_files) == 1


def test_context_manager_rollback_on_exception(ws):
    sandbox = FakeSandbox()
    with pytest.raises(RuntimeError):
        with edit_transaction(sandbox, ws) as tx:
            tx.edit_file("a.py", "return 1", "return 999")
            raise RuntimeError("模拟失败")
    assert "return 1" in (ws / "a.py").read_text()