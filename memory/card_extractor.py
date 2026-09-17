"""从对话历史提炼 Advanced JSON Cards。"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from memory.cards import Card, CardRepository

_EXTRACT_PROMPT = """你是一个记忆提炼器。从下面的对话历史中，提炼出值得长期记住的"卡片"。

## 卡片类型

- **preference**：用户的偏好（"我喜欢…"、"以后都这样"）
- **fact**：关于用户或用户环境的事实（"我用 Windows"、"项目用 pytest"）
- **procedure**：可复用的步骤（"做 X 时先 Y 再 Z"）
- **constraint**：明确的约束（"禁止修改 X 目录"、"必须用 Y 工具"）

## 输出格式

严格输出 JSON 数组：

[
  {{
    "fact": "用户偏好简洁回答，不贴代码块",
    "type": "preference",
    "category": "code_style",
    "backstory": "用户在会话中明确说'以后讲代码时不要贴代码块'",
    "person": "self",
    "relationship": "user",
    "evidence": ["用户原话：'以后讲代码时，不要贴代码块，只讲思路'"],
    "confidence": 0.95
  }}
]

## 字段说明

- **fact**：一句话事实，不超过 30 字
- **type**：preference / fact / procedure / constraint
- **category**：code_style / tool_choice / workflow / constraint / context / other
- **backstory**：一句话说明为什么记这条
- **person**：self / colleague / customer / other
- **relationship**：user / family / colleague / other
- **evidence**：用户原话（最多 2 条）
- **confidence**：0-1

没有可提炼的就输出：[]

## 对话历史

{conversation}
"""


def _format_conversation(
    messages: list[BaseMessage],
    max_chars: int = 12000,
) -> str:
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            content = str(content)

        if "tool" in role:
            continue
        if ("ai" in role or "assistant" in role) and getattr(msg, "tool_calls", None):
            continue

        content = content.strip()
        if not content:
            continue
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}] {content}")

    if not lines:
        return ""
    text = "\n".join(lines)
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n...\n" + text[-half:]
    return text


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "cards" in data:
            return data["cards"]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


def extract_cards(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    session_id: str = "",
) -> list[Card]:
    conversation = _format_conversation(messages)
    if not conversation:
        return []

    prompt = _EXTRACT_PROMPT.format(conversation=conversation)
    try:
        response = llm.invoke(prompt)
        content = getattr(response, "content", "")
        if not isinstance(content, str):
            content = str(content)
    except Exception:
        return []

    raw_cards = _parse_json_array(content)
    if not raw_cards:
        return []

    cards: list[Card] = []
    for rc in raw_cards:
        if not isinstance(rc, dict):
            continue
        fact = str(rc.get("fact", "")).strip()
        if not fact:
            continue
        cards.append(
            Card(
                fact=fact[:200],
                type=rc.get("type", "preference"),
                category=rc.get("category", "other"),
                backstory=str(rc.get("backstory", ""))[:300],
                person=rc.get("person", "self"),
                relationship=rc.get("relationship", "user"),
                evidence=[str(e)[:300] for e in (rc.get("evidence") or [])[:3]],
                source_sessions=[session_id] if session_id else [],
                confidence=float(rc.get("confidence", 0.8)),
            )
        )
    return cards


def _normalize_fact(fact: str) -> str:
    s = fact.strip().lower()
    s = re.sub(r"[\s，。、；：,.]+", "", s)
    return s


def merge_cards_into_repo(
    repo: CardRepository,
    new_cards: list[Card],
) -> tuple[int, int]:
    """把新卡片合并进 repo。返回 (新增数, 跳过数)。"""
    existing = repo.load_active()
    existing_normalized = {_normalize_fact(c.fact) for c in existing}

    added = 0
    skipped = 0
    for card in new_cards:
        n = _normalize_fact(card.fact)
        if not n or n in existing_normalized:
            skipped += 1
            continue
        repo.add(card)
        existing_normalized.add(n)
        added += 1
    return added, skipped


def extract_and_save(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    session_id: str = "",
    repo: CardRepository | None = None,
) -> tuple[int, int]:
    """提炼 + 保存 + 去重。"""
    cards = extract_cards(llm, messages, session_id=session_id)
    if not cards:
        return 0, 0
    if repo is None:
        from memory.cards import user_card_repo

        repo = user_card_repo()
    return merge_cards_into_repo(repo, cards)
