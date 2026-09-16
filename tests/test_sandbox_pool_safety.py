"""沙箱池安全性测试。

关键断言：release 方法绝不能包含任何文件删除操作。

这是之前删文件事故的回归护栏。
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from sandbox.pool import SandboxPool

# ============================================================
# 源码级静态检查
# ============================================================


def test_release_source_has_no_delete():
    """release 方法的源码里不能有 rm / find / delete / sb.exec。"""
    src = inspect.getsource(SandboxPool.release)
    src_lower = src.lower()

    forbidden = [
        "rm -rf",
        "rm -f",
        "rm -r",
        "find /workspace",
        "sb.exec(",
        ".exec(",
        "shutil.rmtree",
        "os.remove",
        "os.unlink",
        "unlink(",
    ]

    for bad in forbidden:
        assert bad not in src_lower, (
            f"release 方法里不应出现 {bad!r}，这是删用户文件的信号。完整源码：\n{src}"
        )


def test_pool_module_has_no_rm_rf():
    """整个 pool.py 模块里不能有 rm -rf 命令。"""
    import sandbox.pool as pool_module

    src = inspect.getsource(pool_module)
    # 允许在 docstring 里提到（比如解释历史）
    code_lines = [
        line
        for line in src.splitlines()
        if not line.strip().startswith("#") and "'''" not in line and '"""' not in line
    ]
    code = "\n".join(code_lines)

    assert "rm -rf" not in code, "pool.py 代码里不应有 rm -rf"


# ============================================================
# 运行时行为检查
# ============================================================


def test_release_only_calls_stop():
    """release 只调用 sb.stop()，不做其他事。"""
    pool = SandboxPool()
    mock_sb = MagicMock()

    pool.release(mock_sb)

    # 断言调用了 stop
    mock_sb.stop.assert_called_once()
    # 断言没有调用 exec
    mock_sb.exec.assert_not_called()


def test_release_none_safe():
    """release(None) 不应崩溃。"""
    pool = SandboxPool()
    pool.release(None)  # 不应抛异常


def test_release_swallows_stop_exception():
    """sb.stop() 抛异常时 release 不应传播。"""
    pool = SandboxPool()
    mock_sb = MagicMock()
    mock_sb.stop.side_effect = RuntimeError("container gone")

    # 不应抛异常
    pool.release(mock_sb)


# ============================================================
# start / shutdown 幂等
# ============================================================


def test_start_idempotent():
    pool = SandboxPool()
    pool.start()
    pool.start()  # 第二次不应抛异常


def test_shutdown_idempotent():
    pool = SandboxPool()
    pool.shutdown()
    pool.shutdown()
