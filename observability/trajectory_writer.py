# observability/trajectory_writer.py
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path


# 模块级 sentinel
_STOP = object()


class TrajectoryWriter:
    """轨迹写入器（异步 + 可轮换）。

    队列元素类型：
      - tuple[str, dict]                  正常事件
      - _STOP                             停止信号
      - tuple("__ROTATE__", str, Event)   轮换信号
      - tuple("__FLUSH__", Event)         强制 flush
    """

    def __init__(self, session_id: str, base_dir: str):
        self.session_id = session_id
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / f"{session_id}.jsonl"

        self._q: queue.Queue = queue.Queue(maxsize=20000)
        self._thread = threading.Thread(
            target=self._run, name="traj-writer", daemon=True
        )
        self._thread.start()

    # ---------- 公开 API ----------

    def append(self, event: str, data: dict) -> None:
        try:
            self._q.put_nowait((event, data))
        except queue.Full:
            pass

    def rotate(self, new_session_id: str, timeout: float = 5.0) -> None:
        """切换到新文件。

        语义：
          - 旧 buffer 先 flush 到旧文件
          - 新文件打开后，之后 append 的事件进新文件
          - 返回时 self.path 已更新

        并发安全：返回后可以放心读 self.path。
        """
        ack = threading.Event()
        try:
            self._q.put_nowait(("__ROTATE__", new_session_id, ack))
        except queue.Full:
            raise RuntimeError("队列满，无法 rotate")
        if not ack.wait(timeout):
            raise TimeoutError(f"rotate 超时 ({timeout}s)")

    def flush_now(self, timeout: float = 2.0) -> None:
        """强制把当前 buffer flush 到磁盘。返回后可以从文件读最新内容。"""
        ack = threading.Event()
        try:
            self._q.put_nowait(("__FLUSH__", ack))
        except queue.Full:
            return
        ack.wait(timeout)

    def close(self) -> None:
        try:
            self._q.put_nowait(_STOP)
        except queue.Full:
            pass
        self._thread.join(timeout=5.0)

    def join(self, timeout: float = 5.0) -> None:
        self._thread.join(timeout=timeout)

    # ---------- 后台线程 ----------

    def _run(self) -> None:
        buf: list[str] = []
        last_flush = time.time()
        f = self.path.open("a", encoding="utf-8")
        try:
            while True:
                try:
                    item = self._q.get(timeout=0.5)
                except queue.Empty:
                    item = None

                # ---- 超时 → flush 缓冲 ----
                if item is None:
                    if buf or time.time() - last_flush > 0.5:
                        self._flush(f, buf)
                        buf = []
                        last_flush = time.time()
                    continue

                # ---- 停止 ----
                if item is _STOP:
                    self._flush(f, buf)
                    buf = []
                    break

                # ---- 轮换 ----
                if isinstance(item, tuple) and item and item[0] == "__ROTATE__":
                    _, new_id, ack = item
                    self._flush(f, buf)
                    buf = []
                    try:
                        f.close()
                    except Exception:
                        pass
                    self.session_id = new_id
                    self.path = self.base_dir / f"{new_id}.jsonl"
                    f = self.path.open("a", encoding="utf-8")
                    try:
                        ack.set()
                    except Exception:
                        pass
                    continue

                # ---- 强制 flush ----
                if isinstance(item, tuple) and item and item[0] == "__FLUSH__":
                    _, ack = item
                    self._flush(f, buf)
                    buf = []
                    last_flush = time.time()
                    try:
                        ack.set()
                    except Exception:
                        pass
                    continue

                # ---- 正常事件 ----
                event, data = item
                record = {"event": event, "ts": time.time(), **data}
                buf.append(json.dumps(record, ensure_ascii=False))

                if len(buf) >= 100:
                    self._flush(f, buf)
                    buf = []
                    last_flush = time.time()
        finally:
            try:
                self._flush(f, buf)
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass

    @staticmethod
    def _flush(f, buf: list[str]) -> None:
        if not buf:
            return
        f.write("\n".join(buf) + "\n")
        f.flush()