"""P1-2: Reviewer 审查工具。

`review_changes` 工具：
  1. 从沙箱收集证据（git diff / git status）
  2. 调用独立 Reviewer 子 Agent
  3. 返回结构化判定（JSON 字符串）

工具是 Agent **主动**调用的——审查成本高，
只有完成非平凡修改后才值得跑一遍。
"""

from __future__ import annotations

import json

from langchain.tools import tool

from sandbox.base import Sandbox

_SANDBOX: Sandbox | None = None
_REVIEWER = None   # agent.reviewer.Reviewer 实例


def bind(sandbox: Sandbox, reviewer) -> None:
    global _SANDBOX, _REVIEWER
    _SANDBOX = sandbox
    _REVIEWER = reviewer


@tool
def review_changes(
    task_description: str,
    test_output: str = "",
) -> str:
    """提交本次改动给独立 Reviewer 审查。

    在完成一个非平凡的代码修改后调用此工具，让 Reviewer 独立判断：
    - 改动是否完成了任务需求
    - 是否引入回归或副作用
    - 是否有冗余或危险操作

    Reviewer 会读取 git diff 和 git status，结合你提供的测试结果做出判断。

    如果返回的 verdict 是 "reject"，请根据 issues 里的具体问题修正后重新审查。

    Args:
        task_description: 用户的原始需求，用于判断改动是否完整。
        test_output: 可选。最近的测试结果（如果你跑过测试）。格式不限，摘要即可。

    Returns:
        JSON 字符串：{"verdict": "approve"|"reject"|"needs_human",
                     "confidence": 0.0-1.0,
                     "summary": "...",
                     "issues": [...],
                     "suggestions": [...]}
    """
    if _SANDBOX is None:
        return json.dumps({"error": "沙箱未绑定"}, ensure_ascii=False)
    if _REVIEWER is None:
        return json.dumps({"error": "Reviewer 未初始化"}, ensure_ascii=False)

    # ---------- 收集证据 ----------
    try:
        diff_res = _SANDBOX.exec("git diff HEAD", timeout=30)
        diff = diff_res.stdout if diff_res.exit_code == 0 else f"(git diff 失败: {diff_res.stderr})"
    except Exception as e:
        diff = f"(git diff 异常: {e})"

    try:
        status_res = _SANDBOX.exec("git status --short", timeout=15)
        status = status_res.stdout if status_res.exit_code == 0 else "(git status 不可用)"
    except Exception as e:
        status = f"(git status 异常: {e})"

    # ---------- 调用 Reviewer ----------
    try:
        verdict = _REVIEWER.review(
            task_description=task_description,
            diff=diff,
            status_output=status,
            test_output=test_output,
        )
    except Exception as e:
        verdict = {
            "verdict": "needs_human",
            "confidence": 0.0,
            "summary": f"Reviewer 调用失败: {e}",
            "issues": [],
            "suggestions": [],
        }

    return json.dumps(verdict, ensure_ascii=False, indent=2)


REVIEW_TOOLS = ["review_changes"]
