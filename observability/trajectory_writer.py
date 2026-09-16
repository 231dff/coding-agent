"""轨迹持久化。

书中 10.4.2：
- 轨迹即 Agent 的全部状态
- 每个会话一个 JSONL 文件
- 支持状态查询、崩溃恢复、事后审计、训练数据
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class TrajectoryWriter:
    """轨迹写入器。每个会话一个 JSONL 文件。"""

    def __init__(
        self,
        session_id: str,
        base_dir: str | Path = ".trajectories",
        buffer_size: int = 1,  # 每条都落盘（保证崩溃时不丢）
    ):
        self.session_id = session_id
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / f"{session_id}.jsonl"

        self._fp = open(self.path, "a", encoding="utf-8")
        self._closed = False

    def append(self, event_type: str, data: dict[str, Any]) -> None:
        """追加一条事件。用 os.write 保证原子性。"""
        if self._closed:
            return
        record = {
            "ts": time.time(),
            "type": event_type,
            "data": data,
        }
        try:
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            os.write(self._fp.fileno(), line.encode("utf-8"))
        except (OSError, TypeError):
            # 落盘失败不阻断主流程
            pass

    def replay(self) -> list[dict]:
        """回放全部事件。"""
        if not self.path.exists():
            return []
        events = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # 崩溃时最后一行可能不完整
                    break
        return events

    def resume_state(self) -> dict:
        """从轨迹重建消息列表。"""
        events = self.replay()
        messages = []
        for e in events:
            if e["type"] == "message":
                messages.append(e["data"])
        return {"messages": messages}

    def last_activity_time(self) -> float:
        """最后一条事件的时间戳。用于检测卡住。"""
        events = self.replay()
        return events[-1]["ts"] if events else 0.0

    def close(self) -> None:
        if not self._closed:
            self._fp.close()
            self._closed = True

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, *args) -> None:
        self.close()