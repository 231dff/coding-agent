"""工具描述规范检查。

书中 4.2.4：
- 边界条件（NOT for）往往比能力描述更重要
- 大多数工具调用失败的根因是模型不知道工具不能做什么
- 长度应控制在 120 tokens 以内

模式：
- strict=True：详细报告所有不合规工具，抛 ValueError
- strict=False：只统计一行，不刷屏
"""
from __future__ import annotations

from langchain.tools import BaseTool


REQUIRED_SECTIONS = ["Boundary", "Params", "Returns", "Failures"]
MAX_DESC_CHARS = 500  # 约 120 tokens


def lint_tool(tool: BaseTool) -> list[str]:
    """检查单个工具描述。返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    desc = tool.description or ""

    # 1. 必需段落
    for section in REQUIRED_SECTIONS:
        if f"### {section}" not in desc:
            errors.append(f"缺少 '### {section}' 段")

    # 2. 边界：必须至少有一个反例
    if "### Boundary" in desc:
        boundary_start = desc.find("### Boundary")
        boundary_end = desc.find("###", boundary_start + 1)
        boundary_text = (
            desc[boundary_start:boundary_end]
            if boundary_end > 0
            else desc[boundary_start:]
        )
        if not any(
            kw in boundary_text for kw in ("NOT for", "不适用于", "不适用")
        ):
            errors.append("Boundary 缺少反例（NOT for / 不适用）")

    # 3. 长度
    if len(desc) > MAX_DESC_CHARS:
        errors.append(f"描述过长（{len(desc)} 字符，建议 ≤ {MAX_DESC_CHARS}）")

    # 4. Markdown 层级：工具描述内只能有 ### 及以下
    for line in desc.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("###"):
            errors.append(
                f"使用了二级标题 '##'（应使用 ### 或更低）: {stripped[:50]}"
            )
            break

    return errors


def validate_tools(tools: list[BaseTool], strict: bool = False) -> dict:
    """批量检查。

    Args:
        tools: 待检查工具列表。
        strict: True → 详细报告 + 抛异常；False → 只统计一行。

    Returns:
        {工具名: 错误列表}。空 dict 表示全部通过。
    """
    report: dict[str, list[str]] = {}
    for t in tools:
        errors = lint_tool(t)
        if errors:
            report[t.name] = errors

    if not report:
        return report

    if strict:
        # 严格模式：详细报告 + 抛异常
        msg = "工具描述不合规：\n"
        for name, errs in report.items():
            msg += f"\n  [{name}]\n"
            for e in errs:
                msg += f"    - {e}\n"
        raise ValueError(msg)

    # 非严格模式：一行统计
    total = len(tools)
    failed = len(report)
    print(
        f"[lint] {failed}/{total} 个工具描述缺规范段落"
        f"（非 strict 模式，仅提示。设置 AGENT_STRICT_LINT=true 启用严格检查）"
    )
    return report


def auto_generate_boundary(tool_name: str, description: str) -> str:
    """为工具生成默认的 Boundary 段（供人工审查后补入）。"""
    return f"""
### Boundary
- NOT for: {_guess_not_for(tool_name)}
- Requires: 见工具参数说明
"""


def _guess_not_for(tool_name: str) -> str:
    """根据工具名推断反例场景。"""
    mapping = {
        "read_file": "不知道路径 → 用 grep_search 或 glob_files",
        "write_file": "修改已有文件 → 用 edit_file",
        "edit_file": "批量多文件修改 → 用 begin_transaction",
        "grep_search": "语义模糊查询 → 用 semantic_search",
        "execute": "读取文件内容 → 用 read_file",
        "semantic_search": "精确正则匹配 → 用 grep_search",
        "run_tests": "任意 shell 命令 → 用 execute",
    }
    return mapping.get(tool_name, "非本工具职责的场景")