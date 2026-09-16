"""Day 13: 事务测试。"""

import pytest

from sandbox.base import ExecResult, Sandbox
from sandbox.transaction import EditTransaction, edit_transaction


class FakeSandbox(Sandbox):
    """测试用的假沙箱，直接操作本地文件。"""

    def start(self):
        pass

    def stop(self):
        pass

    def exec(self, command, timeout=60, cwd=None, env=None):
        return ExecResult(0, "", "", 0.0)

    def read_file(self, path):
        return ""

    def write_file(self, path, content):
        pass

    def upload_dir(self, local, remote):
        pass

    def download_dir(self, remote, local):
        pass


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
    # 替换整句，保持语法完整
    ok, _ = tx.edit_file("b.py", "print(foo())", "print(foo())  # updated")
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


def test_transaction_atomic_all_or_nothing(ws):
    """事务原子性：一个文件语法错，整体回滚。"""
    sandbox = FakeSandbox()
    tx = EditTransaction(sandbox, ws)
    tx.begin()

    # a.py 正常修改
    ok, _ = tx.edit_file("a.py", "return 1", "return 2")
    assert ok

    # b.py 引入语法错误
    ok, _ = tx.edit_file("b.py", "print(foo())", "print(foo(")
    assert ok

    result = tx.commit()
    # 整体失败，a.py 也应回滚
    assert not result.ok
    assert "return 1" in (ws / "a.py").read_text()


def test_context_manager_rollback_on_exception(ws):
    """异常时自动回滚。"""
    sandbox = FakeSandbox()
    try:
        with edit_transaction(sandbox, ws) as tx:
            tx.edit_file("a.py", "return 1", "return 999")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    # 异常退出后，文件应回滚
    assert "return 1" in (ws / "a.py").read_text()
