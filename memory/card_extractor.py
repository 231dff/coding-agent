"""从对话历史提炼 Advanced JSON Cards。

质量过滤（2026-10-06 新增）：
- confidence 阈值：低于 0.7 的丢弃
- 相似度去重：difflib ratio > 0.85 视为重复
- prompt 加规则：禁止记一次性动作、闲聊、常识
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from memory.cards import Card, CardRepository

# ★ 质量阈值
MIN_CONFIDENCE = 0.7
DUPLICATE_RATIO = 0.85

_EXTRACT_PROMPT = """你是一个记忆提炼器。从下面的对话历史中，提炼出值得长期记住的"卡片"。

## 卡片类型

- **preference**：用户的偏好（"我喜欢…"、"以后都这样"）
- **fact**：关于用户或用户环境的事实（"我用 Windows"、"项目用 pytest"）
- **procedure**：可复用的步骤（"做 X 时先 Y 再 Z"）
- **constraint**：明确的约束（"禁止修改 X 目录"、"必须用 Y 工具"）

## ⚠️ 绝对禁止提取的内容

**不要提取**以下 4 类——它们不是稳定的用户属性：

1. **一次性动作**："用户让我写个快排" / "用户问了 n 皇后问题"
2. **闲聊与寒暄**："用户说你好" / "用户表示感谢"
3. **常识与通识**："Python 是解释型语言" / "git 是版本控制"
4. **会话临时状态**："用户现在在调试" / "用户遇到了 bug"

**只有满足"未来 3 个月可能仍然成立"的信息才提取。**

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
- **confidence**：**必须诚实**。只有用户明确说出来的（"我喜欢…"、"以后都…"）才是 0.9+；
  从上下文推断的最多 0.75；不确定的 < 0.7（会被丢弃）

**没有可提炼的就输出：[]**

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

        # ★ 质量过滤 1：confidence 阈值
        try:
            conf = float(rc.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        if conf < MIN_CONFIDENCE:
            continue

        # ★ 质量过滤 2：fact 长度合理性
        if len(fact) < 4 or len(fact) > 100:
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
                confidence=conf,
            )
        )
    return cards


def _normalize_fact(fact: str) -> str:
    s = fact.strip().lower()
    s = re.sub(r"[\s，。、；：,.]+", "", s)
    return s


def _is_duplicate(card: Card, existing_facts: list[str]) -> bool:
    """★ 语义去重：difflib 相似度 > 阈值视为重复。"""
    norm_new = _normalize_fact(card.fact)
    if not norm_new:
        return False

    for existing in existing_facts:
        norm_existing = _normalize_fact(existing)
        if not norm_existing:
            continue
        # 完全一样：直接重复
        if norm_new == norm_existing:
            return True
        # ★ 相似度判断
        ratio = difflib.SequenceMatcher(None, norm_new, norm_existing).ratio()
        if ratio >= DUPLICATE_RATIO:
            return True
    return False


def merge_cards_into_repo(
    repo: CardRepository,
    new_cards: list[Card],
) -> tuple[int, int]:
    """把新卡片合并进 repo。返回 (新增数, 跳过数)。

    跳过原因：
    - confidence 低于阈值（在 extract_cards 已过滤）
    - 与已有卡片重复（完全一样 / 相似度 ≥ 0.85）
    """
    existing = repo.load_active()
    existing_facts = [c.fact for c in existing]

    added = 0
    skipped = 0
    for card in new_cards:
        if _is_duplicate(card, existing_facts):
            skipped += 1
            continue
        repo.add(card)
        existing_facts.append(card.fact)  # 防止同批内重复
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
