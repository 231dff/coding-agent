"""Pending 标记：记录"会话已结束但还没提炼"的任务。

用途：
- 会话结束时写 pending，异步线程尝试提炼
- 如果异步线程被强杀（用户 Ctrl+C 或关终端），pending 保留
- 下次启动时检查 pending，补跑

存储：<project>/.coding-agent/memory/pending.jsonl
append-only，完成一个任务就重写一次（清掉已完成的）
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PendingTask:
    """一条待提炼任务。"""

    thread_id: str
    project_path: str
    user_id: str
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PendingTask":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def pending_path(meta_dir: Path) -> Path:
    """pending 文件路径。"""
    return meta_dir / "memory" / "pending.jsonl"


def add_pending(meta_dir: Path, task: PendingTask) -> None:
    """追加一个 pending 任务。"""
    path = pending_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")


def load_pending(meta_dir: Path) -> list[PendingTask]:
    """加载所有 pending 任务（容错，跳过坏行）。"""
    path = pending_path(meta_dir)
    if not path.is_file():
        return []

    tasks: list[PendingTask] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    tasks.append(PendingTask.from_dict(json.loads(line)))
                except Exception:
                    continue
    except Exception:
        return []
    return tasks


def remove_pending(meta_dir: Path, thread_id: str) -> None:
    """移除指定 thread 的 pending 标记。"""
    path = pending_path(meta_dir)
    if not path.is_file():
        return

    remaining = [t for t in load_pending(meta_dir) if t.thread_id != thread_id]

    try:
        with path.open("w", encoding="utf-8") as f:
            for t in remaining:
                f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass


def clear_all_pending(meta_dir: Path) -> None:
    """清空所有 pending（调试用）。"""
    path = pending_path(meta_dir)
    if path.is_file():
        try:
            path.write_text("", encoding="utf-8")
        except Exception:
            pass
