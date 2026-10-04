"""独立 Reviewer 子 Agent。

原则（书中第八章）：
  Reviewer 的价值不在"重读代码"，而在"看到生成时不存在的信息"。
  因此它的输入是：git diff + 测试结果 + 任务描述，不共享主 Agent 的轨迹。
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


REVIEWER_SYSTEM_PROMPT = """你是一个独立的代码审查员。你的职责是基于**已发生的事实**独立判断本次改动是否合格。

**你只能基于输入中的证据判断，不能臆测。** 输入中包含：
- 任务描述（用户原始需求）
- git diff（实际改动）
- git status（新增/删除的文件）
- 测试结果（如果有）

**审查标准**（按优先级）：
1. 完整性：是否完成了任务描述中的全部需求？
2. 正确性：测试是否全部通过？改动是否引入明显 bug 或回归？
3. 最小性：是否修改了不必要的文件？是否有冗余改动？
4. 安全性：是否引入危险操作（删文件、改配置、绕过测试、泄露信息）？
5. 承诺—行动一致性：如果 diff 声称修复了某个问题，实际代码是否真的改了对应的位置？

**你必须返回严格 JSON，格式如下**：
{
  "verdict": "approve" | "reject" | "needs_human",
  "confidence": 0.0,
  "summary": "一句话总结",
  "issues": [
    {
      "severity": "critical" | "major" | "minor",
      "description": "具体问题描述",
      "evidence": "来自 diff 或测试结果的具体行/位置"
    }
  ],
  "suggestions": ["可执行的修复建议1", "建议2"]
}

**判定规则**：
- 有 critical issue → reject
- 有 major issue → reject
- 只有 minor issue 或没有 issue → approve
- 证据不足以判断（比如 diff 为空、测试结果与改动无关）→ needs_human

**边界情况**：
- 空 diff：如果任务要求修改但 diff 为空 → reject（说明没做）
- 只加不改：如果只新增文件、不改现有文件 → 检查是否合理
- 修改测试文件：这是 red flag，需要在 issues 中明确指出
- 删除文件：默认 needs_human，除非任务明确要求删除

输出必须是**纯 JSON**，不要 Markdown 代码块，不要额外说明。
"""


class Reviewer:
    """独立 Reviewer 子 Agent。"""

    def __init__(self, llm):
        self.llm = llm

    def review(
        self,
        task_description: str,
        diff: str,
        status_output: str = "",
        test_output: str = "",
    ) -> dict[str, Any]:
        """
        Returns:
            dict with keys: verdict, confidence, summary, issues, suggestions
            解析失败时返回 verdict="needs_human"
        """
        prompt = self._build_prompt(
            task_description, diff, status_output, test_output
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            raw = self._extract_content(response)
        except Exception as e:
            return {
                "verdict": "needs_human",
                "confidence": 0.0,
                "summary": f"Reviewer LLM 调用失败: {e}",
                "issues": [],
                "suggestions": [],
            }

        return self._parse_json(raw)

    # ---------- 内部 ----------

    @staticmethod
    def _extract_content(response) -> str:
        c = getattr(response, "content", "")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for block in c:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return str(c)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """解析 Reviewer 返回的 JSON，容错处理 Markdown 代码块包裹。"""
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    data = None

        if not isinstance(data, dict):
            return {
                "verdict": "needs_human",
                "confidence": 0.0,
                "summary": "Reviewer 返回非 JSON，无法解析",
                "issues": [],
                "suggestions": [],
                "raw": raw[:1000],
            }

        if data.get("verdict") not in ("approve", "reject", "needs_human"):
            data["verdict"] = "needs_human"
        data.setdefault("confidence", 0.5)
        data.setdefault("summary", "")
        data.setdefault("issues", [])
        data.setdefault("suggestions", [])
        return data

    @staticmethod
    def _build_prompt(
        task_description: str,
        diff: str,
        status_output: str,
        test_output: str,
    ) -> str:
        MAX_DIFF = 8000
        MAX_TEST = 2000

        diff_display = diff if len(diff) <= MAX_DIFF else (
            diff[:MAX_DIFF] + f"\n... (diff 已截断，共 {len(diff)} 字符)"
        )
        test_display = test_output if len(test_output) <= MAX_TEST else (
            test_output[:MAX_TEST] + "... (truncated)"
        )

        parts = [
            "## 任务描述",
            task_description or "(空)",
            "",
            "## git diff HEAD",
            diff_display or "(空——没有实际改动)",
            "",
            "## git status",
            status_output or "(空)",
        ]
        if test_output:
            parts.extend([
                "",
                "## 最近的测试结果",
                test_display,
            ])
        parts.append("")
        parts.append("请基于以上事实输出严格 JSON。")

        return "\n".join(parts)