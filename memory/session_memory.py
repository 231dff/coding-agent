"""Day 26: 会话级记忆。

与项目记忆互补：
- 项目记忆：长期、跨项目、以文件形式（AGENTS.md）
- 会话记忆：短期、跨 thread、以 Store 形式
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from langgraph.store.base import BaseStore


@dataclass
class SessionRecord:
    """一条会话记录。"""
    thread_id: str
    user_id: str
    task: str
    outcome: str                   # success | failure | partial
    files_changed: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class SessionMemory:
    """会话记忆管理器。

    存储在 LangGraph Store 中：
    - namespace: ("sessions", user_id)
    - key: thread_id
    """

    NAMESPACE_PREFIX = "sessions"
    LESSONS_NAMESPACE = "lessons"

    def __init__(self, store: BaseStore):
        self.store = store

    def record_session(self, record: SessionRecord) -> None:
        """记录一次会话。"""
        namespace = (self.NAMESPACE_PREFIX, record.user_id)
        self.store.put(
            namespace,
            record.thread_id,
            {
                "task": record.task,
                "outcome": record.outcome,
                "files_changed": record.files_changed,
                "lessons": record.lessons,
                "timestamp": record.timestamp,
            },
        )

    def get_recent(self, user_id: str, limit: int = 5) -> list[dict]:
        """获取用户最近的会话。"""
        namespace = (self.NAMESPACE_PREFIX, user_id)
        items = self.store.search(namespace, limit=limit)
        return [item.value for item in items]

    def add_lesson(self, lesson: str, tags: list[str] | None = None) -> None:
        """添加一条跨会话的教训。

        教训与项目记忆的差异：
        - 项目记忆：与具体项目绑定
        - 教训：跨项目、与 Agent 自身行为相关
        """
        key = f"lesson_{int(time.time() * 1000)}"
        self.store.put(
            (self.LESSONS_NAMESPACE,),
            key,
            {
                "text": lesson,
                "tags": tags or [],
                "timestamp": time.time(),
            },
        )

    def relevant_lessons(self, query: str, limit: int = 3) -> list[str]:
        """检索与当前任务相关的教训。

        生产环境应使用向量检索。这里先用简单关键词过滤。
        """
        items = self.store.search((self.LESSONS_NAMESPACE,), limit=50)
        query_words = set(query.lower().split())

        scored = []
        for item in items:
            text = item.value.get("text", "")
            tags = set(item.value.get("tags", []))
            text_words = set(text.lower().split())

            # 关键词命中数
            overlap = len(query_words & (text_words | tags))
            if overlap > 0:
                scored.append((overlap, text))

        scored.sort(reverse=True)
        return [t for _, t in scored[:limit]]