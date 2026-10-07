"""会话摘要存储（第 2 层记忆的原始数据）。

数据分层（2026-10-07 新增）：
  - level="raw"   每次任务产生一条，永不删除
  - level="daily" 由 N 条 raw 聚合而来，带 source_ids 引用

聚合后 raw 摘要保留在 store 里，打上 aggregated_into 标记。
检索时优先命中 daily，避免噪声。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.store.base import BaseStore

from memory.store import current_user_id, get_store


@dataclass
class SessionSummary:
    """一次会话的摘要。"""

    session_id: str
    summary: str
    task_type: str = "other"
    user_id: str = "default"
    project_path: str = ""
    key_facts: list[str] = field(default_factory=list)
    success: bool = True
    timestamp: float = 0.0
    id: str = ""

    # ★ 聚合相关字段
    level: str = "raw"                                    # raw / daily
    source_ids: list[str] = field(default_factory=list)   # 被聚合的原始摘要 ID
    aggregated_into: str = ""                             # 已被聚到哪个父摘要

    def __post_init__(self):
        if not self.id:
            self.id = f"sum-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSummary":
        """向后兼容：旧数据缺新字段时用默认值。"""
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class SessionSummaryRepository:
    """会话摘要仓库（基于 LangGraph Store）。"""

    def __init__(self, store: BaseStore, user_id: str = "default"):
        self.store = store
        self.user_id = user_id

    def _ns(self) -> tuple[str, ...]:
        return ("users", self.user_id, "summaries")

    # ---------- 写 ----------

    def add(self, item: SessionSummary) -> SessionSummary:
        self.store.put(self._ns(), item.id, item.to_dict())
        return item

    def mark_aggregated(self, ids: list[str], parent_id: str) -> int:
        """批量标记摘要为已聚合。返回更新数量。"""
        if not ids or not parent_id:
            return 0
        ids_set = set(ids)
        updated = 0
        for s in self.load_all():
            if s.id not in ids_set:
                continue
            s.aggregated_into = parent_id
            try:
                self.store.put(self._ns(), s.id, s.to_dict())
                updated += 1
            except Exception:
                continue
        return updated

    # ---------- 读 ----------

    def load_all(self) -> list[SessionSummary]:
        """加载所有摘要（raw + daily）。"""
        try:
            items = self.store.search(self._ns(), limit=10000)
        except Exception:
            return []

        summaries: list[SessionSummary] = []
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            try:
                summaries.append(SessionSummary.from_dict(value))
            except Exception:
                continue
        return summaries

    # ★ 新增：只返回"可检索"的摘要（排除已聚合的 raw）
    def load_searchable(self) -> list[SessionSummary]:
        """返回检索时应该看到的摘要：

        - 所有 daily 摘要（聚合后的浓缩）
        - 未聚合的 raw 摘要（新鲜事件）

        已聚合的 raw 不返回——内容已在 daily 里。
        """
        all_summaries = self.load_all()
        return [
            s for s in all_summaries
            if s.level == "daily" or not s.aggregated_into
        ]

    def find_unaggregated_raw(self, limit: int = 1000) -> list[SessionSummary]:
        """找所有 level=raw 且 aggregated_into 为空的摘要。"""
        all_summaries = self.load_all()
        result = [
            s for s in all_summaries
            if s.level == "raw" and not s.aggregated_into
        ]
        result.sort(key=lambda x: x.timestamp)
        return result[:limit]

    def recent(self, n: int = 50) -> list[SessionSummary]:
        items = self.load_all()
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items[:n]

    def search(self, query: str, limit: int = 5) -> list[SessionSummary]:
        """语义 / 关键词搜索（Store 原生）。"""
        try:
            items = self.store.search(self._ns(), query=query, limit=limit)
        except Exception:
            return []

        summaries: list[SessionSummary] = []
        for item in items:
            value = item.value
            if not isinstance(value, dict):
                continue
            try:
                summaries.append(SessionSummary.from_dict(value))
            except Exception:
                continue
        return summaries


def session_summary_repo(user_id: str | None = None) -> SessionSummaryRepository:
    uid = user_id or current_user_id()
    return SessionSummaryRepository(get_store(), user_id=uid)


# ============================================================
# 摘要生成（未改动）
# ============================================================

_SUMMARY_PROMPT = """请从下面的对话历史中，生成一段 200 字以内的会话摘要。

需要包含：
- 用户要求做什么（一句话）
- 用什么方法/工具做的
- 结果如何（成功/失败/部分完成）

同时给出：
- task_type：从 debug / refactor / explain / implement / research / other 里选一个
- key_facts：最多 3 条关键事实（短语）

严格输出 JSON：

{{
  "summary": "...",
  "task_type": "...",
  "key_facts": ["...", "..."],
  "success": true
}}

## 对话历史

{conversation}
"""


def _format_conversation(
    messages: list[BaseMessage],
    max_chars: int = 8000,
) -> str:
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            content = str(content)
        if "tool" in role:
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > 400:
            content = content[:400] + "..."
        lines.append(f"[{role}] {content}")

    if not lines:
        return ""
    text = "\n".join(lines)
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n...\n" + text[-half:]
    return text


def summarize_session(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    session_id: str,
    user_id: str = "default",
    project_path: str = "",
) -> SessionSummary | None:
    """用 LLM 生成会话摘要。"""
    import json
    import re

    conversation = _format_conversation(messages)
    if not conversation:
        return None

    prompt = _SUMMARY_PROMPT.format(conversation=conversation)
    try:
        response = llm.invoke(prompt)
        content = getattr(response, "content", "")
        if not isinstance(content, str):
            content = str(content)
    except Exception:
        return None

    text = content.strip()
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    return SessionSummary(
        session_id=session_id,
        summary=str(data.get("summary", ""))[:500],
        task_type=str(data.get("task_type", "other")),
        user_id=user_id,
        project_path=project_path,
        key_facts=[str(x)[:100] for x in (data.get("key_facts") or [])[:5]],
        success=bool(data.get("success", True)),
        level="raw",
    )
