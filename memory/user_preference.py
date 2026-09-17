"""用户偏好提炼与存储。

流程：
    会话结束 → 读当前会话所有消息 → 轻量模型提炼偏好
        → 追加到 <project>/.coding-agent/memory/user.md
        → 下次启动时注入 system prompt

设计原则：
- 只在会话结束时提炼，运行中不改文件（KV Cache 友好）
- 用轻量模型（AGENT_COMPACTION_MODEL），成本可控
- 行级去重，避免重复写入相同偏好
- 最多保留 N 条，超出时按类别均摊截断
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

# ============================================================
# 存储路径
# ============================================================


def user_memory_path(meta_dir: Path) -> Path:
    """返回用户偏好文件路径。"""
    return meta_dir / "memory" / "user.md"


def load_user_memory(meta_dir: Path) -> str:
    """读取用户偏好内容。不存在时返回空字符串。"""
    path = user_memory_path(meta_dir)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# ============================================================
# 提炼提示词
# ============================================================

_EXTRACT_PROMPT = """你是一个用户偏好分析器。请从下面的对话历史中，提炼出值得长期记住的"用户偏好"。

## 判断标准

只记录：
- 用户明确表达的偏好（"我喜欢…"、"以后都这样…"、"不要…"）
- 反复出现的工作习惯（连续 2 次以上同类操作）
- 明确的约束（"这个项目禁止…"、"必须用…"）
- 代码风格偏好（命名、框架、工具选择）

不要记录：
- 一次性任务的具体内容（"读完 README"）
- 临时上下文（"现在在看 analysis_agent.py"）
- 通用编程常识（"要用类型注解"——除非用户明确强调）
- 模型自己说过的话

## 输出格式

按类别输出 Markdown 列表。没有偏好就输出"（无）"，不要硬凑。

格式示例：

## 代码风格
- 偏好 1

## 工作习惯
- 偏好 2

## 工具选择
- 偏好 3

## 明确约束
- 偏好 4

每条不超过 30 字，最多 8 条。宁可少写，不要编造。

## 对话历史

{conversation}
"""


# ============================================================
# 提炼
# ============================================================


def _format_messages_for_extraction(
    messages: list[BaseMessage],
    max_chars: int = 12000,
) -> str:
    """把消息列表格式化成提炼提示词里的对话文本。

    截断策略：从头尾各取一半，中间省略。
    跳过工具调用/结果（噪音大）。
    """
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            content = str(content)

        # 跳过工具调用/结果（噪音大）
        if "tool" in role:
            continue
        # 跳过带 tool_calls 的 AI 消息
        if "ai" in role or "assistant" in role:
            if getattr(msg, "tool_calls", None):
                continue

        content = content.strip()
        if not content:
            continue

        # 单条截断
        if len(content) > 500:
            content = content[:500] + "..."

        lines.append(f"[{role}] {content}")

    if not lines:
        return ""

    text = "\n".join(lines)

    # 总长截断：头尾各一半
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + "\n...\n" + text[-half:]

    return text


def extract_preferences(
    llm: BaseChatModel,
    messages: list[BaseMessage],
) -> str:
    """从对话历史里提炼用户偏好。

    Args:
        llm: 轻量模型（推荐用压缩模型）。
        messages: 当前会话的所有消息。

    Returns:
        Markdown 格式的偏好文本。失败或无内容时返回空字符串。
    """
    conversation = _format_messages_for_extraction(messages)
    if not conversation:
        return ""

    prompt = _EXTRACT_PROMPT.format(conversation=conversation)

    try:
        response = llm.invoke(prompt)
        content = getattr(response, "content", "")
        if not isinstance(content, str):
            content = str(content)
        return _clean_extracted(content)
    except Exception:
        return ""


def _clean_extracted(text: str) -> str:
    """清理 LLM 输出：去掉围栏、去掉"（无）"、去掉空标题。"""
    text = text.strip()

    # 去掉 markdown 围栏
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    # 无内容判断
    if not text or text in ("（无）", "(无)", "无"):
        return ""
    if re.fullmatch(r"[（(]?无[）)]?", text):
        return ""

    # 去掉空标题（## XXX 后面没有任何 - 条目）
    lines = text.splitlines()
    cleaned: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            j = i + 1
            has_item = False
            while j < len(lines) and not lines[j].startswith("#"):
                if lines[j].strip().startswith("-"):
                    has_item = True
                    break
                j += 1
            if has_item:
                cleaned.append(line)
        else:
            cleaned.append(line)
        i += 1

    return "\n".join(cleaned).strip()


# ============================================================
# 写入 + 去重
# ============================================================


def _normalize_line(line: str) -> str:
    """归一化一行，用于去重判断。"""
    s = line.strip().lstrip("-").strip().lower()
    s = re.sub(r"[\s，。、；：]+", "", s)
    return s


def merge_into_user_memory(
    meta_dir: Path,
    new_content: str,
    max_lines: int = 40,
) -> str:
    """把新提炼的偏好合并进 user.md。

    策略：
    - 按类别分组
    - 行级去重（归一化后完全相同则丢弃）
    - 超过 max_lines 时，按类别均摊截断（保留最早写的）

    Returns:
        合并后的完整文本。
    """
    path = user_memory_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_user_memory(meta_dir)

    existing_groups = _parse_md_groups(existing)
    new_groups = _parse_md_groups(new_content)

    merged: dict[str, list[str]] = {}
    seen_normalized: set[str] = set()

    # 先加旧的
    for cat, lines in existing_groups.items():
        merged.setdefault(cat, [])
        for line in lines:
            n = _normalize_line(line)
            if n and n not in seen_normalized:
                merged[cat].append(line)
                seen_normalized.add(n)

    # 再加新的（跳过重复）
    for cat, lines in new_groups.items():
        merged.setdefault(cat, [])
        for line in lines:
            n = _normalize_line(line)
            if n and n not in seen_normalized:
                merged[cat].append(line)
                seen_normalized.add(n)

    output_lines = ["# 用户偏好", ""]

    total = sum(len(v) for v in merged.values())
    if total > max_lines:
        per_cat = max(1, max_lines // max(1, len(merged)))
        for cat in merged:
            merged[cat] = merged[cat][:per_cat]

    for cat, lines in merged.items():
        if not lines:
            continue
        output_lines.append(f"## {cat}")
        for line in lines:
            if not line.strip().startswith("-"):
                line = f"- {line.strip()}"
            output_lines.append(line)
        output_lines.append("")

    result = "\n".join(output_lines).rstrip() + "\n"
    path.write_text(result, encoding="utf-8")
    return result


def _parse_md_groups(text: str) -> dict[str, list[str]]:
    """把 Markdown 解析成 {category: [lines]}。"""
    groups: dict[str, list[str]] = {}
    current_cat: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            current_cat = stripped[3:].strip()
            groups.setdefault(current_cat, [])
        elif stripped.startswith("# "):
            continue
        elif stripped.startswith("- ") and current_cat:
            groups[current_cat].append(stripped)

    return groups


def stats(meta_dir: Path) -> dict:
    """返回用户偏好文件的统计信息（调试用）。"""
    path = user_memory_path(meta_dir)
    if not path.is_file():
        return {"exists": False, "lines": 0, "categories": 0}

    text = path.read_text(encoding="utf-8")
    groups = _parse_md_groups(text)
    return {
        "exists": True,
        "path": str(path),
        "lines": sum(len(v) for v in groups.values()),
        "categories": len(groups),
    }
