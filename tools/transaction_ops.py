"""Day 13: 事务工具的 LangChain 封装。

提供 begin_transaction / tx_edit / tx_commit / tx_rollback 四个工具。
Agent 在多次编辑时显式使用事务。
"""

from __future__ import annotations

from langchain.tools import tool

from sandbox.base import Sandbox
from sandbox.transaction import EditTransaction

_TX: EditTransaction | None = None
_SANDBOX: Sandbox | None = None
_WORKSPACE: str | None = None


def bind(sandbox: Sandbox, workspace: str) -> None:
    global _SANDBOX, _WORKSPACE
    _SANDBOX = sandbox
    _WORKSPACE = workspace


@tool
def begin_transaction() -> str:
    """开始一个多文件编辑事务。

    当需要同时修改多个文件（如重命名、接口变更）时，ALWAYS 先调用此工具。
    在事务内所有修改都不会立即生效，直到 commit。
    """
    global _TX
    if _SANDBOX is None or _WORKSPACE is None:
        return "ERROR: 事务未初始化"
    if _TX is not None and _TX._active:
        return "ERROR: 已有活跃事务，请先 commit 或 rollback"
    _TX = EditTransaction(_SANDBOX, _WORKSPACE)
    _TX.begin()
    return f"事务已开启 (id={_TX.tx_id})"


@tool
def tx_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """在事务内编辑文件。修改进入暂存区，不影响原文件。

    Args:
        path: 文件路径。
        old_string: 原文本。
        new_string: 新文本。
        replace_all: 是否替换所有匹配。
    """
    if _TX is None or not _TX._active:
        return "ERROR: 没有活跃事务，请先 begin_transaction"
    ok, msg = _TX.edit_file(path, old_string, new_string, replace_all)
    return ("OK: " if ok else "ERROR: ") + msg


@tool
def tx_write(path: str, content: str) -> str:
    """在事务内写入文件（覆盖）。

    Args:
        path: 文件路径。
        content: 新内容。
    """
    if _TX is None or not _TX._active:
        return "ERROR: 没有活跃事务，请先 begin_transaction"
    ok, msg = _TX.write_file(path, content)
    return ("OK: " if ok else "ERROR: ") + msg


@tool
def tx_commit() -> str:
    """提交事务。所有修改原子生效，语法错误自动回滚。"""
    global _TX
    if _TX is None or not _TX._active:
        return "ERROR: 没有活跃事务"
    result = _TX.commit(syntax_check=True)
    _TX = None

    if result.ok:
        files = ", ".join(result.edited_files)
        return f"事务提交成功，修改了 {len(result.edited_files)} 个文件: {files}"
    else:
        errs = "; ".join(result.errors)
        rollback_msg = "（已自动回滚）" if result.rolled_back else ""
        return f"事务失败 {rollback_msg}: {errs}"


@tool
def tx_rollback() -> str:
    """回滚事务，丢弃所有未提交的修改。"""
    global _TX
    if _TX is None or not _TX._active:
        return "ERROR: 没有活跃事务"
    _TX.rollback()
    _TX = None
    return "事务已回滚"


TRANSACTION_TOOLS = ["begin_transaction", "tx_edit", "tx_write", "tx_commit", "tx_rollback"]
