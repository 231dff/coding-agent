"""结果层验证：区分『修改类任务』与『查询类任务』。

支持两种 run_tests 证据来源：
  1. 独立 tool_result: {name: "run_tests", output: "..."}
  2. 附加在写操作返回里: {name: "write_file", output: "...=== AutoTest Results ===..."}
"""

from __future__ import annotations

import re

from .events import TrajEvent
from .schema import DimensionResult, Evidence, Severity, Verdict

AUTO_TEST_MARKER = "=== AutoTest Results ==="
_AUTO_TEST_OK_RE = re.compile(r"测试结果:\s*✓ 全部通过")
_AUTO_TEST_FAIL_RE = re.compile(r"测试结果:\s*✗ 存在失败")


class ResultVerifier:
    EXIT_CHECKED_TOOLS = {"execute", "run_tests", "run_python"}
    WRITE_TOOLS = {"write_file", "edit_file", "apply_patch", "sandbox_write"}

    def verify(self, events: list[TrajEvent]) -> DimensionResult:
        # ---------- 1. 拦截"带错误的执行" ----------
        broken = [
            e
            for e in events
            if e.type == "tool_result"
            and e.name in self.EXIT_CHECKED_TOOLS
            and (e.has_oci_error or (e.exit_code is not None and e.exit_code != 0))
        ]
        if broken:
            evidence = [
                Evidence(
                    line_no=e.line_no,
                    ts=e.ts,
                    tool_name=e.name,
                    tool_call_id=e.tool_call_id,
                    quote=(e.output_raw or "")[:200],
                    source="environment",
                )
                for e in broken[:5]
            ]
            return DimensionResult(
                name="task_result",
                verdict=Verdict.FAIL,
                severity=Severity.HIGH,
                confidence=1.0,
                reason=(
                    f"{len(broken)} 次执行失败但 success 被误标为 true, "
                    f"示例: L{broken[0].line_no} {broken[0].name} "
                    f"EXIT={broken[0].exit_code} oci={broken[0].has_oci_error}"
                ),
                evidence=evidence,
                metadata={"broken_count": len(broken)},
            )

        # ---------- 2. 识别任务类型 ----------
        wrote_files = any(
            e.type == "tool_result" and e.name in self.WRITE_TOOLS and e.success is True
            for e in events
        )

        # ---------- 3. 修改类任务：必须有测试通过证据 ----------
        if wrote_files:
            test_evidence, failures = self._collect_test_evidence(events)

            if not test_evidence:
                return DimensionResult(
                    name="task_result",
                    verdict=Verdict.UNCERTAIN,
                    severity=Severity.HIGH,
                    confidence=0.5,
                    reason="修改了文件但未跑测试（无 run_tests 也无 AutoTest 标记）",
                    evidence=[
                        Evidence(
                            source="trajectory",
                            quote="wrote_files=True, test_evidence=0",
                        )
                    ],
                )

            if failures:
                return DimensionResult(
                    name="task_result",
                    verdict=Verdict.FAIL,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    reason="; ".join(failures),
                    evidence=test_evidence,
                )
            return DimensionResult(
                name="task_result",
                verdict=Verdict.PASS,
                severity=Severity.HIGH,
                confidence=1.0,
                reason=f"修改类任务，{len(test_evidence)} 条测试证据全部通过",
                evidence=test_evidence,
            )

        # ---------- 4. 查询类任务 ----------
        successful = [e for e in events if e.type == "tool_result" and e.success is True]
        if not successful:
            return DimensionResult(
                name="task_result",
                verdict=Verdict.UNCERTAIN,
                severity=Severity.MEDIUM,
                confidence=0.4,
                reason="没有任何成功的工具调用证据",
            )

        evidence = [
            Evidence(
                line_no=e.line_no,
                ts=e.ts,
                tool_name=e.name,
                tool_call_id=e.tool_call_id,
                quote=(e.content or "")[:120],
                source="tool",
            )
            for e in successful[:5]
        ]
        return DimensionResult(
            name="task_result",
            verdict=Verdict.PASS,
            severity=Severity.HIGH,
            confidence=0.9,
            reason=f"查询类任务，{len(successful)} 次工具调用全部成功",
            evidence=evidence,
        )

    # ---------- 内部 ----------

    def _collect_test_evidence(self, events):
        """收集所有测试证据。返回 (evidence_list, failure_reasons)。"""
        evidence = []
        failures = []

        for e in events:
            if e.type != "tool_result":
                continue
            text = e.content or e.output_raw or ""

            # 来源 1: 独立 run_tests
            if e.name == "run_tests":
                ok = bool(_AUTO_TEST_OK_RE.search(text))
                evidence.append(
                    Evidence(
                        line_no=e.line_no,
                        ts=e.ts,
                        tool_name="run_tests",
                        tool_call_id=e.tool_call_id,
                        quote=text[:200],
                        source="tool",
                    )
                )
                if not ok:
                    failures.append(f"L{e.line_no} run_tests 未通过")

            # 来源 2: 写操作返回值里含 AutoTest 标记
            elif e.name in self.WRITE_TOOLS and AUTO_TEST_MARKER in text:
                # 提取 AutoTest 段
                idx = text.find(AUTO_TEST_MARKER)
                tail = text[idx : idx + 500]
                ok = bool(_AUTO_TEST_OK_RE.search(tail))
                failed = bool(_AUTO_TEST_FAIL_RE.search(tail))
                evidence.append(
                    Evidence(
                        line_no=e.line_no,
                        ts=e.ts,
                        tool_name=f"{e.name}+AutoTest",
                        tool_call_id=e.tool_call_id,
                        quote=tail[:200],
                        source="tool",
                    )
                )
                if failed or not ok:
                    failures.append(f"L{e.line_no} AutoTest 未通过")

        return evidence, failures
