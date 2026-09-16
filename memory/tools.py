"""Day 26: 记忆工具的 LangChain 封装。"""
from __future__ import annotations

from langchain.tools import tool

from memory.project_memory import ProjectMemory


_PROJECT_MEMORY: ProjectMemory | None = None


def bind(workspace: str) -> None:
    global _PROJECT_MEMORY
    _PROJECT_MEMORY = ProjectMemory(workspace)
    _PROJECT_MEMORY.ensure_initialized()


@tool
def update_memory(section: str, text: str) -> str:
    """向项目记忆 (AGENTS.md) 添加一条约定。

    ALWAYS 在以下场景更新记忆：
    - 发现项目使用的包管理器、测试命令、构建命令
    - 确认编码规范、命名约定、目录结构约定
    - 踩到一个坑并找到 workaround
    - 用户明确说明禁止事项

    条目要求：
    - 简短：≤ 200 字符
    - 可执行：以 ALWAYS / NEVER / 祈使句表述
    - 与行动相关：不用记流水账

    Args:
        section: 分区名，推荐 "Build & Test" / "Conventions" /
                 "Constraints" / "Known Issues"。
        text: 条目文本，如 "ALWAYS 用 uv 而非 pip"。
    """
    if _PROJECT_MEMORY is None:
        return "ERROR: 项目记忆未初始化"

    added = _PROJECT_MEMORY.add(section, text)
    if added:
        return f"OK: 已添加 [{section}] {text}"
    return f"SKIP: 条目已存在或无效"


@tool
def read_memory(section: str = "") -> str:
    """读取项目记忆。

    Args:
        section: 可选，只读取指定分区。
    """
    if _PROJECT_MEMORY is None:
        return "ERROR: 项目记忆未初始化"

    content = _PROJECT_MEMORY.load()
    if not content:
        return "(项目记忆为空)"

    if not section:
        return content

    # 提取指定 section
    lines = content.splitlines()
    in_section = False
    result: list[str] = []
    for line in lines:
        if line.startswith("## "):
            in_section = line[3:].strip() == section
            if in_section:
                result.append(line)
        elif in_section:
            result.append(line)

    return "\n".join(result) if result else f"(未找到分区: {section})"


MEMORY_TOOLS = ["update_memory", "read_memory"]