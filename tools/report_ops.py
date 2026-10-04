"""P1-3: 结构化交付报告。

`generate_summary_report` 工具：
  1. 收集事实：git diff --stat / 新增删除文件 / 最近的测试结果
  2. 生成 Markdown 报告
  3. 同时保存到 .coding-agent/reports/<timestamp>.md
  4. 返回 Markdown 文本（供 Agent 直接展示给用户）

设计原则：
  - 纯事实，不含主观判断
  - 结构化，便于人工审计
  - 持久化，便于回溯
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain.tools import tool

from sandbox.base import Sandbox

_SANDBOX: Sandbox | None = None
_REPORT_DIR: Path | None = None


def bind(sandbox: Sandbox, report_dir: Path | str) -> None:
    global _SANDBOX, _REPORT_DIR
    _SANDBOX = sandbox
    _REPORT_DIR = Path(report_dir)


@tool
def generate_summary_report(
    task_description: str,
    summary: str,
    test_output: str = "",
    reviewer_verdict: str = "",
) -> str:
    """生成本次任务的结构化交付报告。

    在任务**全部完成**（包括必要的审查）后调用此工具。
    它会收集 git 事实、测试结果、审查结论，产出一份 Markdown 报告，
    并保存到磁盘。

    在最终回复用户之前调用一次即可，不要重复调用。

    Args:
        task_description: 用户的原始需求。
        summary: 你对本次任务的简短总结（1-3 句话）。
        test_output: 最近的测试结果（如果有）。
        reviewer_verdict: Reviewer 的 verdict（approve/reject/needs_human），
                         或完整 JSON 字符串。没有审查时可以留空。

    Returns:
        Markdown 格式的报告（可直接展示给用户）。
    """
    if _SANDBOX is None:
        return "ERROR: 沙箱未绑定"

    now = datetime.now()

    # ---------- 收集 git 事实 ----------
    diff_stat = _safe_exec("git diff HEAD --stat", timeout=15)
    status_short = _safe_exec("git status --short", timeout=10)
    changed_files = _extract_changed_files(status_short)

    # ---------- 提取审查结论 ----------
    review_line = _format_review(reviewer_verdict)

    # ---------- 组装 Markdown ----------
    lines = [
        "# 任务交付报告",
        "",
        f"**时间**: {now:%Y-%m-%d %H:%M:%S}",
        "",
        "## 任务需求",
        "",
        task_description or "(未提供)",
        "",
        "## 执行摘要",
        "",
        summary or "(未提供)",
        "",
        "## 改动文件",
        "",
    ]

    if changed_files:
        for status, path in changed_files:
            lines.append(f"- `{status}` {path}")
    else:
        lines.append("(无改动)")

    lines.extend([
        "",
        "## 改动统计",
        "",
        "```",
        diff_stat.strip() or "(无 diff)",
        "```",
        "",
    ])

    if test_output:
        lines.extend([
            "## 测试结果",
            "",
            "```",
            test_output.strip()[:1500],
            "```",
            "",
        ])

    if review_line:
        lines.extend([
            "## 审查结论",
            "",
            review_line,
            "",
        ])

    report = "\n".join(lines)

    # ---------- 保存到磁盘 ----------
    saved_path = _save_report(report, now)

    # ---------- 附加保存路径 ----------
    if saved_path:
        report += f"\n\n---\n_报告已保存: {saved_path}_"

    return report


# ---------- 内部 ----------

def _safe_exec(cmd: str, timeout: int = 15) -> str:
    try:
        result = _SANDBOX.exec(cmd, timeout=timeout)
        if result.exit_code == 0:
            return result.stdout
        return f"(命令失败 exit={result.exit_code}: {result.stderr[:200]})"
    except Exception as e:
        return f"(执行异常: {e})"


def _extract_changed_files(status_output: str) -> list[tuple[str, str]]:
    """从 `git status --short` 输出里提取 (status, path) 列表。"""
    files = []
    for line in status_output.splitlines():
        line = line.rstrip()
        if not line or len(line) < 3:
            continue
        status = line[:2].strip() or "?"
        path = line[3:].strip()
        if path:
            files.append((status, path))
    return files


def _format_review(reviewer_verdict: str) -> str:
    """把 Reviewer 的 verdict 格式化为 Markdown 列表项。"""
    if not reviewer_verdict:
        return ""

    # 尝试解析 JSON
    try:
        data = json.loads(reviewer_verdict)
        if isinstance(data, dict) and "verdict" in data:
            lines = [
                f"- **判定**: `{data.get('verdict', '?')}`",
                f"- **置信度**: {data.get('confidence', 0.0):.2f}",
            ]
            summary = data.get("summary", "")
            if summary:
                lines.append(f"- **总结**: {summary}")
            issues = data.get("issues", [])
            if issues:
                lines.append(f"- **问题** ({len(issues)} 条):")
                for iss in issues[:5]:
                    sev = iss.get("severity", "?")
                    desc = iss.get("description", "")
                    lines.append(f"  - `[{sev}]` {desc}")
            suggestions = data.get("suggestions", [])
            if suggestions:
                lines.append("- **建议**:")
                for s in suggestions[:3]:
                    lines.append(f"  - {s}")
            return "\n".join(lines)
    except (json.JSONDecodeError, TypeError):
        pass

    # 不是 JSON，当作字符串
    return f"- **判定**: `{reviewer_verdict.strip()[:200]}`"


def _save_report(report: str, now: datetime) -> str | None:
    """保存报告到磁盘，返回相对路径。"""
    if _REPORT_DIR is None:
        return None

    try:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"report-{now:%Y%m%d-%H%M%S}.md"
        path = _REPORT_DIR / filename
        path.write_text(report, encoding="utf-8")
        return f".coding-agent/reports/{filename}"
    except Exception as e:
        return f"(保存失败: {e})"


REPORT_TOOLS = ["generate_summary_report"]
