# observability/trajectory_writer.py
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path


class TrajectoryWriter:
    def __init__(self, session_id: str, base_dir: str):
        self.session_id = session_id
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / f"{session_id}.jsonl"

        self._q: queue.Queue[tuple[str, dict] | None] = queue.Queue(maxsize=20000)
        self._thread = threading.Thread(target=self._run, name="traj-writer", daemon=True)
        self._thread.start()

    def append(self, event: str, data: dict) -> None:
        try:
            self._q.put_nowait((event, data))
        except queue.Full:
            pass

    def _run(self) -> None:
        buf = []
        last_flush = time.time()
        f = self.path.open("a", encoding="utf-8")
        try:
            while True:
                try:
                    item = self._q.get(timeout=0.5)
                except queue.Empty:
                    item = None

                if item is None:
                    if buf or time.time() - last_flush > 0.5:
                        self._flush(f, buf)
                        buf = []
                        last_flush = time.time()
                    continue

                event, data = item
                record = {"event": event, "ts": time.time(), **data}
                buf.append(json.dumps(record, ensure_ascii=False))

                if len(buf) >= 100:
                    self._flush(f, buf)
                    buf = []
                    last_flush = time.time()
        finally:
            self._flush(f, buf)
            f.close()

    @staticmethod
    def _flush(f, buf: list[str]) -> None:
        if not buf:
            return
        f.write("\n".join(buf) + "\n")
        f.flush()

    def close(self) -> None:
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
