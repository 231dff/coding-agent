"""Day 13: 编辑事务。

核心机制：
1. 编辑前在沙箱内创建临时副本
2. 所有修改在副本中完成
3. commit 时校验语法 + 原子替换
4. 失败自动回滚
"""

from __future__ import annotations

import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sandbox.base import Sandbox


@dataclass
class EditRecord:
    """一次编辑记录。"""

    path: str
    old_content: str
    new_content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class TransactionResult:
    """事务执行结果。"""

    ok: bool
    edited_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rolled_back: bool = False


class EditTransaction:
    """多文件编辑事务。

    生命周期：
        tx = EditTransaction(sandbox, workspace)
        tx.begin()
        tx.edit_file("a.py", "old", "new")
        tx.edit_file("b.py", "old", "new")
        result = tx.commit()  # 或 tx.rollback()
    """

    def __init__(self, sandbox: Sandbox, workspace: str | Path):
        self.sandbox = sandbox
        self.workspace = Path(workspace).resolve()
        self.tx_id = uuid.uuid4().hex[:8]
        self.staging_dir = self.workspace / f".tx_{self.tx_id}"
        self.backup_dir = self.workspace / f".tx_{self.tx_id}_backup"
        self._edits: list[EditRecord] = []
        self._active = False

    def begin(self) -> None:
        """开启事务。"""
        if self._active:
            raise RuntimeError("事务已激活")
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._active = True
        self._edits = []

    def edit_file(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> tuple[bool, str]:
        """在事务内编辑文件。修改进入 staging，不影响原文件。"""
        if not self._active:
            raise RuntimeError("事务未激活")

        # 读取原始内容
        src = self.workspace / path
        if not src.is_file():
            return False, f"文件不存在: {path}"

        current = src.read_text(encoding="utf-8")

        # 计算修改后的内容
        count = current.count(old_string)
        if count == 0:
            return False, f"未找到匹配文本于 {path}"
        if count > 1 and not replace_all:
            return False, f"{path} 中 old_string 出现 {count} 次，不唯一"

        new_content = (
            current.replace(old_string, new_string)
            if replace_all
            else current.replace(old_string, new_string, 1)
        )

        # 记录编辑（staging 内容只存内存，commit 时才落盘）
        self._edits.append(
            EditRecord(
                path=path,
                old_content=current,
                new_content=new_content,
            )
        )
        return True, f"已暂存 {path} 的修改"

    def write_file(self, path: str, content: str) -> tuple[bool, str]:
        """在事务内写入文件（覆盖）。"""
        if not self._active:
            raise RuntimeError("事务未激活")

        src = self.workspace / path
        old = src.read_text(encoding="utf-8") if src.is_file() else ""

        self._edits.append(
            EditRecord(
                path=path,
                old_content=old,
                new_content=content,
            )
        )
        return True, f"已暂存 {path} 的写入"

    def commit(self, syntax_check: bool = True) -> TransactionResult:
        """提交事务。

        流程：
        1. 语法校验（在 staging 中）
        2. 备份原文件
        3. 原子写入所有新内容
        4. 任何失败则回滚
        """
        if not self._active:
            raise RuntimeError("事务未激活")

        result = TransactionResult(ok=False)

        # 1. 语法校验（针对 .py 文件）
        if syntax_check:
            for edit in self._edits:
                if edit.path.endswith(".py"):
                    err = self._check_python_syntax(edit.path, edit.new_content)
                    if err:
                        result.errors.append(f"{edit.path}: {err}")
                        self.rollback()
                        result.rolled_back = True
                        return result

        # 2. 备份所有涉及的文件
        for edit in self._edits:
            src = self.workspace / edit.path
            if src.is_file():
                backup = self.backup_dir / edit.path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, backup)

        # 3. 原子写入
        written: list[str] = []
        try:
            for edit in self._edits:
                dst = self.workspace / edit.path
                dst.parent.mkdir(parents=True, exist_ok=True)
                # 写临时文件 + rename 保证原子性
                tmp = dst.with_suffix(dst.suffix + f".tx_{self.tx_id}")
                tmp.write_text(edit.new_content, encoding="utf-8")
                tmp.replace(dst)
                written.append(edit.path)
        except Exception as e:
            result.errors.append(f"写入失败: {e}")
            # 回滚已写入的
            self._restore_from_backup(written)
            self.rollback()
            result.rolled_back = True
            return result

        result.ok = True
        result.edited_files = written
        self._cleanup()
        self._active = False
        return result

    def rollback(self) -> None:
        """回滚事务，删除 staging 与备份。"""
        self._cleanup()
        self._active = False
        self._edits = []

    def _restore_from_backup(self, files: list[str]) -> None:
        """从备份恢复指定文件。"""
        for path in files:
            backup = self.backup_dir / path
            if backup.is_file():
                shutil.copy2(backup, self.workspace / path)

    def _cleanup(self) -> None:
        """清理临时目录。"""
        for d in (self.staging_dir, self.backup_dir):
            shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def _check_python_syntax(path: str, content: str) -> str | None:
        """校验 Python 语法。返回错误信息或 None。"""
        import ast

        try:
            ast.parse(content, filename=path)
            return None
        except SyntaxError as e:
            return f"语法错误 line {e.lineno}: {e.msg}"


@contextmanager
def edit_transaction(sandbox: Sandbox, workspace: str | Path):
    """便捷的上下文管理器。

    用法:
        with edit_transaction(sandbox, ws) as tx:
            tx.edit_file("a.py", "old", "new")
            tx.edit_file("b.py", "old", "new")
            result = tx.commit()
    """
    tx = EditTransaction(sandbox, workspace)
    tx.begin()
    try:
        yield tx
    except Exception:
        tx.rollback()
        raise
    finally:
        if tx._active:
            tx.rollback()
