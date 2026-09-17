"""检索器：直接复用 Store 的 search 能力。

Store 后端支持语义搜索（Postgres + pgvector）时，走语义；
SQLite 或内存后端时，退化为关键词匹配。
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.session_summary import (
    SessionSummary,
    session_summary_repo,
)


@dataclass
class RetrievedItem:
    session_id: str
    summary: str
    score: float
    timestamp: float
    task_type: str


class StoreRetriever:
    """基于 LangGraph Store 的检索器。"""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.repo = session_summary_repo(user_id=user_id)

    def index(self, item: SessionSummary) -> None:
        """写入时自动被索引（Store.put 已处理）。"""
        # 无需额外操作，Store 的 put 就是索引
        pass

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
        user_id: str = "",
    ) -> list[RetrievedItem]:
        """按语义 / 关键词检索。"""
        if user_id and user_id != self.user_id:
            repo = session_summary_repo(user_id=user_id)
        else:
            repo = self.repo

        try:
            summaries = repo.search(query, limit=top_k)
        except Exception:
            return []

        items: list[RetrievedItem] = []
        for i, s in enumerate(summaries):
            # Store 不返回分数，用排名倒推
            score = 1.0 / (i + 1)
            if score < min_score:
                continue
            items.append(
                RetrievedItem(
                    session_id=s.session_id,
                    summary=s.summary,
                    score=round(score, 3),
                    timestamp=s.timestamp,
                    task_type=s.task_type,
                )
            )
        return items


_RETRIEVER: StoreRetriever | None = None


def get_retriever(user_id: str = "default") -> StoreRetriever:
    global _RETRIEVER
    if _RETRIEVER is None or _RETRIEVER.user_id != user_id:
        _RETRIEVER = StoreRetriever(user_id=user_id)
    return _RETRIEVER
