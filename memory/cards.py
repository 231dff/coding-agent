"""Advanced JSON Cards：第 1 层记忆。

数据模型：Card 数据类（8 字段）
存储：基于 LangGraph Store 的 CardRepository

命名空间约定：
    ("users", user_id, "cards", "active")   当前有效卡片
    ("users", user_id, "cards", "history")  历史版本（supersedes 链）
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

from langgraph.store.base import BaseStore

from memory.store import current_user_id, get_store

CardType = Literal["preference", "fact", "procedure", "constraint", "deleted"]
CardScope = Literal["user", "project", "knowledge"]


@dataclass
class Card:
    """Advanced JSON Card。"""

    fact: str
    type: CardType = "preference"
    category: str = "other"

    backstory: str = ""
    person: str = "self"
    relationship: str = "user"

    evidence: list[str] = field(default_factory=list)
    source_sessions: list[str] = field(default_factory=list)

    id: str = ""
    scope: CardScope = "user"
    confidence: float = 0.9
    created_at: float = 0.0
    updated_at: float = 0.0
    version: int = 1
    supersedes: str | None = None

    def __post_init__(self):
        if not self.id:
            self.id = f"card-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def to_prompt_line(self) -> str:
        return f"- [{self.category}] {self.fact}"


# ============================================================
# CardRepository（基于 LangGraph Store）
# ============================================================


class CardRepository:
    """卡片仓库。

    所有操作走 LangGraph Store，换后端不改代码。
    """

    def __init__(self, store: BaseStore, user_id: str = "default"):
        self.store = store
        self.user_id = user_id

    # ---------- 命名空间 ----------

    def _ns_active(self) -> tuple[str, ...]:
        return ("users", self.user_id, "cards", "active")

    def _ns_history(self) -> tuple[str, ...]:
        return ("users", self.user_id, "cards", "history")

    def _ns_all_versions(self) -> tuple[str, ...]:
        return ("users", self.user_id, "cards")

    # ---------- 读 ----------

    def load_all_versions(self) -> list[Card]:
        """加载所有版本（用于 supersede 检查）。"""
        cards: list[Card] = []
        try:
            items = self.store.search(self._ns_all_versions(), limit=10000)
        except Exception:
            return []

        seen_ids: set[str] = set()
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            try:
                card = Card.from_dict(value)
                if card.id not in seen_ids:
                    seen_ids.add(card.id)
                    cards.append(card)
            except Exception:
                continue
        return cards

    def load_active(self) -> list[Card]:
        """返回当前有效卡片。"""
        all_cards = self.load_all_versions()

        superseded: set[str] = set()
        for c in all_cards:
            if c.supersedes:
                superseded.add(c.supersedes)

        return [c for c in all_cards if c.id not in superseded and c.type != "deleted"]

    def get(self, card_id: str) -> Card | None:
        """按 ID 精确查找。"""
        try:
            item = self.store.get(self._ns_active(), card_id)
        except Exception:
            return None
        if item is None:
            return None
        value = item.value
        if not isinstance(value, dict):
            return None
        try:
            return Card.from_dict(value)
        except Exception:
            return None

    # ---------- 写 ----------

    def add(self, card: Card) -> Card:
        """追加一张卡片。"""
        self.store.put(
            self._ns_active(),
            card.id,
            card.to_dict(),
        )
        return card

    def update(
        self,
        old_id: str,
        new_fact: str,
        **overrides,
    ) -> Card:
        """更新一张卡片（追加新版本 + supersedes）。"""
        old = self.get(old_id)
        if old is None:
            raise ValueError(f"卡片不存在: {old_id}")

        new = Card(
            fact=new_fact,
            type=overrides.get("type", old.type),
            category=overrides.get("category", old.category),
            backstory=overrides.get("backstory", old.backstory),
            person=overrides.get("person", old.person),
            relationship=overrides.get("relationship", old.relationship),
            evidence=overrides.get("evidence", old.evidence),
            source_sessions=overrides.get("source_sessions", old.source_sessions),
            scope=old.scope,
            confidence=overrides.get("confidence", old.confidence),
            version=old.version + 1,
            supersedes=old_id,
        )

        # 新版本入 active
        self.store.put(
            self._ns_active(),
            new.id,
            new.to_dict(),
        )
        # 旧版本挪到 history
        self.store.put(
            self._ns_history(),
            old.id,
            old.to_dict(),
        )
        # 从 active 删掉旧的
        try:
            self.store.delete(self._ns_active(), old_id)
        except Exception:
            pass

        return new

    def delete(self, card_id: str) -> Card:
        """软删除（写入 tombstone）。"""
        old = self.get(card_id)
        if old is None:
            raise ValueError(f"卡片不存在: {card_id}")

        tombstone = Card(
            fact=f"[DELETED] {old.fact}",
            type="deleted",  # type: ignore
            category=old.category,
            scope=old.scope,
            supersedes=card_id,
        )
        self.add(tombstone)
        try:
            self.store.delete(self._ns_active(), card_id)
        except Exception:
            pass
        return tombstone

    # ---------- 查询 ----------

    def find_by_category(self, category: str) -> list[Card]:
        return [c for c in self.load_active() if c.category == category]

    def find_by_type(self, card_type: str) -> list[Card]:
        return [c for c in self.load_active() if c.type == card_type]

    def search(self, query: str, limit: int = 5) -> list[Card]:
        """语义 / 关键词搜索（依赖 Store 后端能力）。"""
        try:
            items = self.store.search(
                self._ns_active(),
                query=query,
                limit=limit,
            )
        except Exception:
            return []

        cards: list[Card] = []
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            try:
                cards.append(Card.from_dict(value))
            except Exception:
                continue
        return cards

    # ---------- 渲染 ----------

    def render_prompt(
        self,
        max_cards: int = 40,
        min_confidence: float = 0.5,
    ) -> str:
        """渲染成 system prompt 片段。"""
        cards = [c for c in self.load_active() if c.confidence >= min_confidence]
        if not cards:
            return ""

        groups: dict[str, list[Card]] = {}
        for c in cards:
            groups.setdefault(c.category, []).append(c)
        for cat in groups:
            groups[cat].sort(key=lambda c: c.confidence, reverse=True)

        total = 0
        lines: list[str] = []
        for cat, items in groups.items():
            if total >= max_cards:
                break
            lines.append(f"## {cat}")
            for c in items:
                if total >= max_cards:
                    break
                lines.append(c.to_prompt_line())
                total += 1
            lines.append("")
        return "\n".join(lines).rstrip()


# ============================================================
# 工厂
# ============================================================


def user_card_repo(user_id: str | None = None) -> CardRepository:
    """用户卡片仓库。"""
    uid = user_id or current_user_id()
    return CardRepository(get_store(), user_id=uid)
