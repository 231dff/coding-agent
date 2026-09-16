"""后台异步索引器。

设计目标：
1. Agent 启动不阻塞——构造即返回，索引在后台线程运行
2. 状态可查询——pending / indexing / ready / failed
3. 索引未就绪时，工具返回有指导性的提示而非空错误
4. 优雅停止——进程退出或 Agent 关闭时能 join 后台线程
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from codebase.parser import CodeParser

if TYPE_CHECKING:
    from codebase.indexer import CodeIndexer


class IndexStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class IndexProgress:
    """索引进度快照。"""
    total: int = 0
    done: int = 0
    current_file: str = ""
    chunks_indexed: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def to_text(self) -> str:
        if self.done == 0 and self.total == 0:
            return "索引尚未开始"
        pct = int(100 * self.done / self.total) if self.total else 0
        lines = [
            f"进度: {self.done}/{self.total} ({pct}%)",
            f"已索引块: {self.chunks_indexed}",
            f"耗时: {self.elapsed():.1f}s",
        ]
        if self.current_file:
            lines.append(f"当前文件: {self.current_file}")
        if self.error:
            lines.append(f"错误: {self.error}")
        return "\n".join(lines)


class BackgroundIndexer:
    """后台异步索引器。

    用法：
        bg = BackgroundIndexer(parser, indexer)
        bg.start()                # 立即返回
        ...
        if bg.is_ready():
            results = bg.search("query")
    """

    def __init__(
        self,
        parser: CodeParser,
        indexer: CodeIndexer,
        include_patterns: list[str] | None = None,
    ):
        self.parser = parser
        self.indexer = indexer
        self.include_patterns = include_patterns

        self._status = IndexStatus.PENDING
        self._progress = IndexProgress()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._done_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- 生命周期 ----------

    def start(self, background: bool = True) -> None:
        """启动索引。

        Args:
            background: True 则在新线程中运行（推荐），
                        False 则同步执行（用于测试）。
        """
        if self._status != IndexStatus.PENDING:
            return  # 已启动，幂等

        if background:
            self._thread = threading.Thread(
                target=self._run,
                name="bg-indexer",
                daemon=True,
            )
            self._thread.start()
        else:
            self._run()

    def stop(self, timeout: float = 5.0) -> None:
        """请求停止并等待后台线程退出。"""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞等待索引完成。用于测试或需要同步语义的场景。"""
        return self._done_event.wait(timeout=timeout)

    # ---------- 状态查询 ----------

    @property
    def status(self) -> IndexStatus:
        with self._lock:
            return self._status

    def is_ready(self) -> bool:
        return self.status == IndexStatus.READY

    def is_indexing(self) -> bool:
        return self.status == IndexStatus.INDEXING

    def snapshot(self) -> IndexProgress:
        """获取当前进度快照。"""
        with self._lock:
            return IndexProgress(
                total=self._progress.total,
                done=self._progress.done,
                current_file=self._progress.current_file,
                chunks_indexed=self._progress.chunks_indexed,
                started_at=self._progress.started_at,
                finished_at=self._progress.finished_at,
                error=self._progress.error,
            )

    # ---------- 内部实现 ----------

    def _run(self) -> None:
        """后台线程入口。"""
        with self._lock:
            self._status = IndexStatus.INDEXING
            self._progress.started_at = time.time()

        try:
            parsed_files = list(self.parser.parse_all())

            with self._lock:
                self._progress.total = len(parsed_files)

            def on_progress(done: int, total: int, current: str) -> None:
                if self._stop_event.is_set():
                    raise _Stopped()
                with self._lock:
                    self._progress.done = done
                    self._progress.current_file = current

            chunks = self.indexer.index_files(
                parsed_files,
                on_progress=on_progress,
            )

            with self._lock:
                self._progress.chunks_indexed = chunks
                self._progress.finished_at = time.time()
                self._status = IndexStatus.READY

        except _Stopped:
            with self._lock:
                self._status = IndexStatus.FAILED
                self._progress.error = "用户中止"
                self._progress.finished_at = time.time()
        except Exception as e:
            with self._lock:
                self._status = IndexStatus.FAILED
                self._progress.error = str(e)
                self._progress.finished_at = time.time()
        finally:
            self._done_event.set()

    # ---------- 查询代理 ----------

    def search(self, query: str, **kwargs: Any) -> list[dict]:
        """代理到 CodeIndexer.search。

        仅在 READY 状态可用。调用方应先检查 is_ready()。
        """
        if not self.is_ready():
            raise RuntimeError(f"索引未就绪，当前状态: {self.status.value}")
        return self.indexer.search(query, **kwargs)


class _Stopped(Exception):
    """内部信号：后台线程收到停止请求。"""
    pass