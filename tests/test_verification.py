"""三层轨迹验证器单元测试。

覆盖：
  - schema.py: Verdict / Severity / Evidence / DimensionResult / TrajectoryDiagnosis
  - events.py: _parse 双格式兼容、output/error 解析、OCI/EXIT 提取、parse_lines
  - result_verifier.py: 破损执行 / 修改类 / 查询类 / AutoTest 标记
  - process_verifier.py: 规则 / 工具健康 / 承诺-行动
  - quality_verifier.py: 无 judge / 有效 judge / 无效 judge
  - orchestrator.py: 四态聚合 / veto / success / summary
"""

from __future__ import annotations

import json
from pathlib import Path

from verification.events import (
    TrajEvent,
    _parse,
    load_events,
    parse_lines,
)
from verification.orchestrator import TrajectoryVerifier
from verification.process_verifier import ProcessVerifier
from verification.quality_verifier import QualityVerifier
from verification.result_verifier import (
    AUTO_TEST_MARKER,
    ResultVerifier,
)
from verification.schema import (
    DimensionResult,
    Evidence,
    Severity,
    TrajectoryDiagnosis,
    Verdict,
)

# ============================================================
# helpers
# ============================================================


def make_event(
    type_: str = "tool_call",
    name: str | None = None,
    args: dict | None = None,
    success: bool | None = None,
    content: str | None = None,
    output_raw: str | None = None,
    exit_code: int | None = None,
    has_oci_error: bool = False,
    line_no: int = 0,
    ts: float = 0.0,
    tool_call_id: str | None = None,
) -> TrajEvent:
    return TrajEvent(
        line_no=line_no,
        ts=ts,
        type=type_,
        name=name,
        args=args,
        success=success,
        output_raw=output_raw,
        content=content,
        tool_call_id=tool_call_id,
        exit_code=exit_code,
        has_oci_error=has_oci_error,
        raw={},
    )


# ============================================================
# schema.py
# ============================================================


def test_verdict_enum_values():
    assert Verdict.PASS.value == "pass"
    assert Verdict.FAIL.value == "fail"
    assert Verdict.UNCERTAIN.value == "uncertain"


def test_severity_enum_values():
    assert Severity.LOW.value == "low"
    assert Severity.MEDIUM.value == "medium"
    assert Severity.HIGH.value == "high"
    assert Severity.VETO.value == "veto"


def test_dimension_default_severity():
    d = DimensionResult(name="x", verdict=Verdict.PASS)
    assert d.severity == Severity.MEDIUM
    assert d.confidence == 1.0
    assert d.evidence == []


def test_trajectory_diagnosis_add():
    diag = TrajectoryDiagnosis(task_id="t1")
    d = DimensionResult(name="a", verdict=Verdict.PASS)
    diag.add(d)
    assert len(diag.dimensions) == 1
    assert diag.get("a") is d
    assert diag.get("nonexistent") is None


def test_trajectory_diagnosis_veto_triggers_fail():
    """VETO + FAIL → 一票否决。"""
    diag = TrajectoryDiagnosis(task_id="t1")
    diag.add(DimensionResult(
        name="hallucination",
        verdict=Verdict.FAIL,
        severity=Severity.VETO,
    ))
    assert diag.veto_triggered is True
    assert diag.success is False
    assert diag.overall_verdict == Verdict.FAIL


def test_trajectory_diagnosis_high_fail_does_not_trigger_veto():
    """HIGH 的 FAIL 不触发 veto 标志（只触发 overall fail）。"""
    diag = TrajectoryDiagnosis(task_id="t1")
    diag.add(DimensionResult(
        name="x",
        verdict=Verdict.FAIL,
        severity=Severity.HIGH,
    ))
    assert diag.veto_triggered is False


def test_trajectory_diagnosis_requires_human_review_medium():
    """MEDIUM + confidence < 0.6 → 需人工复核。"""
    diag = TrajectoryDiagnosis(task_id="t1")
    diag.add(DimensionResult(
        name="x",
        verdict=Verdict.UNCERTAIN,
        severity=Severity.MEDIUM,
        confidence=0.4,
    ))
    assert diag.requires_human_review is True


def test_trajectory_diagnosis_low_confidence_does_not_trigger():
    """LOW 的 UNCERTAIN → 不触发人工复核。"""
    diag = TrajectoryDiagnosis(task_id="t1")
    diag.add(DimensionResult(
        name="quality_judge",
        verdict=Verdict.UNCERTAIN,
        severity=Severity.LOW,
        confidence=0.0,
    ))
    assert diag.requires_human_review is False


def test_trajectory_diagnosis_high_confidence_no_review():
    diag = TrajectoryDiagnosis(task_id="t1")
    diag.add(DimensionResult(
        name="x",
        verdict=Verdict.UNCERTAIN,
        severity=Severity.HIGH,
        confidence=0.9,
    ))
    assert diag.requires_human_review is False


def test_evidence_defaults():
    e = Evidence()
    assert e.source == "trajectory"
    assert e.line_no is None


# ============================================================
# events.py — _parse 双格式
# ============================================================


def test_parse_new_format_tool_call():
    """新格式：字段在顶层。"""
    rec = {
        "event": "tool_call",
        "ts": 123.4,
        "name": "write_file",
        "args": {"path": "a.py"},
    }
    e = _parse(0, rec)
    assert e.type == "tool_call"
    assert e.name == "write_file"
    assert e.args == {"path": "a.py"}
    assert e.ts == 123.4


def test_parse_old_format_tool_call():
    """旧格式：type + data 嵌套。"""
    rec = {
        "ts": 123.4,
        "type": "tool_call",
        "data": {"name": "read_file", "args": {"path": "a.py"}},
    }
    e = _parse(0, rec)
    assert e.type == "tool_call"
    assert e.name == "read_file"
    assert e.args == {"path": "a.py"}


def test_parse_tool_result_with_content_wrapper():
    """output 里的 content='...' name='...' tool_call_id='...' 被解包。"""
    rec = {
        "event": "tool_result",
        "ts": 1.0,
        "name": "read_file",
        "success": True,
        "output": "content='hello' name='read_file' tool_call_id='call_1'",
    }
    e = _parse(0, rec)
    assert e.name == "read_file"
    assert e.content == "hello"
    assert e.tool_call_id == "call_1"


def test_parse_output_with_exit_code():
    rec = {
        "event": "tool_result",
        "ts": 1.0,
        "name": "execute",
        "success": True,
        "output": "STDOUT: ...\nEXIT: 127",
    }
    e = _parse(0, rec)
    assert e.exit_code == 127


def test_parse_output_with_oci_error():
    rec = {
        "event": "tool_result",
        "ts": 1.0,
        "name": "execute",
        "success": True,
        "output": "OCI runtime exec failed: chdir failed",
    }
    e = _parse(0, rec)
    assert e.has_oci_error is True


def test_parse_error_field_fallback():
    """没有 output 时回退到 error 字段。"""
    rec = {
        "event": "tool_result",
        "ts": 1.0,
        "name": "execute",
        "success": False,
        "error": "command not found",
    }
    e = _parse(0, rec)
    assert e.output_raw == "command not found"
    assert e.success is False


def test_parse_content_fallback_extraction():
    """output 不是标准 wrapper 时，用正则抽 tool_call_id。"""
    rec = {
        "event": "tool_result",
        "ts": 1.0,
        "name": "x",
        "success": True,
        "output": "some text tool_call_id='call_xyz' more text",
    }
    e = _parse(0, rec)
    assert e.tool_call_id == "call_xyz"


# ============================================================
# events.py — iter_events / load_events / parse_lines
# ============================================================


def test_iter_events_skips_blank_and_invalid(tmp_path: Path):
    f = tmp_path / "traj.jsonl"
    f.write_text(
        '{"event": "tool_call", "name": "a"}\n'
        "\n"
        "不是 JSON\n"
        '{"event": "tool_call", "name": "b"}\n',
        encoding="utf-8",
    )
    events = load_events(f)
    assert len(events) == 2
    assert events[0].name == "a"
    assert events[1].name == "b"


def test_parse_lines_basic():
    lines = [
        '{"event": "tool_call", "name": "x"}',
        "",
        '{"event": "tool_result", "name": "x", "success": true}',
    ]
    events = parse_lines(lines)
    assert len(events) == 2


# ============================================================
# result_verifier.py
# ============================================================


def test_result_broken_exec_fails():
    """execute 有 exit_code != 0 → FAIL。"""
    events = [
        make_event(
            type_="tool_result",
            name="execute",
            success=True,
            exit_code=127,
            output_raw="EXIT: 127",
        )
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.FAIL
    assert "执行失败" in r.reason


def test_result_oci_error_fails():
    events = [
        make_event(
            type_="tool_result",
            name="execute",
            success=True,
            has_oci_error=True,
            output_raw="OCI runtime exec failed",
        )
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.FAIL


def test_result_no_evidence_uncertain():
    r = ResultVerifier().verify([])
    assert r.verdict == Verdict.UNCERTAIN


def test_result_write_no_test_uncertain():
    """写了文件但没跑测试 → UNCERTAIN。"""
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.UNCERTAIN
    assert "未跑测试" in r.reason


def test_result_write_with_tests_pass():
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
        make_event(
            type_="tool_result",
            name="run_tests",
            success=True,
            content="测试结果: ✓ 全部通过\n总数: 5, 失败: 0",
        ),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.PASS


def test_result_write_with_tests_fail():
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
        make_event(
            type_="tool_result",
            name="run_tests",
            success=True,
            content="测试结果: ✗ 存在失败\n总数: 5, 失败: 2",
        ),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.FAIL


def test_result_autotest_marker_pass():
    """AutoTest 标记在 write_file 的 output 里 → PASS。"""
    events = [
        make_event(
            type_="tool_result",
            name="write_file",
            success=True,
            content=(
                "OK: 已写入 a.py\n\n"
                f"{AUTO_TEST_MARKER}\n"
                "[工具] write_file\n测试结果: ✓ 全部通过"
            ),
        ),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.PASS


def test_result_autotest_marker_fail():
    events = [
        make_event(
            type_="tool_result",
            name="write_file",
            success=True,
            content=(
                f"{AUTO_TEST_MARKER}\n[工具] write_file\n测试结果: ✗ 存在失败"
            ),
        ),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.FAIL


def test_result_query_task_pass():
    """无写操作，有成功的 tool_result → PASS。"""
    events = [
        make_event(type_="tool_result", name="read_file", success=True, content="hello"),
        make_event(type_="tool_result", name="grep_search", success=True, content="found"),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.PASS
    assert "查询类" in r.reason


def test_result_all_failed_uncertain():
    """所有 tool_result 都失败，无写操作 → UNCERTAIN。"""
    events = [
        make_event(type_="tool_result", name="read_file", success=False),
    ]
    r = ResultVerifier().verify(events)
    assert r.verdict == Verdict.UNCERTAIN


# ============================================================
# process_verifier.py
# ============================================================


def test_process_rules_pass():
    events = [make_event(type_="tool_call", name="read_file", args={"path": "a.py"})]
    pv = ProcessVerifier()
    results = pv.verify(events)
    by_name = {r.name: r for r in results}
    assert by_name["rule_compliance"].verdict == Verdict.PASS


def test_process_rules_forbidden_command():
    events = [make_event(
        type_="tool_call",
        name="execute",
        args={"command": "rm -rf /"},
    )]
    pv = ProcessVerifier()
    results = pv.verify(events)
    by_name = {r.name: r for r in results}
    assert by_name["rule_compliance"].verdict == Verdict.FAIL
    assert "根目录" in by_name["rule_compliance"].reason


def test_process_tool_health_pass():
    events = [
        make_event(type_="tool_result", name="execute", success=True, exit_code=0),
        make_event(type_="tool_result", name="execute", success=True, exit_code=0),
    ]
    pv = ProcessVerifier()
    by_name = {r.name: r for r in pv.verify(events)}
    assert by_name["tool_health"].verdict == Verdict.PASS


def test_process_tool_health_three_failures():
    """同一工具连续失败 ≥3 次 → FAIL。"""
    events = [
        make_event(type_="tool_result", name="execute", success=False, exit_code=1),
        make_event(type_="tool_result", name="execute", success=False, exit_code=1),
        make_event(type_="tool_result", name="execute", success=False, exit_code=1),
    ]
    pv = ProcessVerifier()
    by_name = {r.name: r for r in pv.verify(events)}
    assert by_name["tool_health"].verdict == Verdict.FAIL


def test_process_promise_action_fail():
    """写文件但从未成功执行 → VETO FAIL。"""
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
        make_event(type_="tool_result", name="execute", success=False, exit_code=127),
    ]
    pv = ProcessVerifier()
    by_name = {r.name: r for r in pv.verify(events)}
    r = by_name["promise_action_consistency"]
    assert r.verdict == Verdict.FAIL
    assert r.severity == Severity.VETO


def test_process_promise_action_pass():
    """写文件 + 成功执行 → PASS。"""
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
        make_event(type_="tool_result", name="execute", success=True, exit_code=0),
    ]
    pv = ProcessVerifier()
    by_name = {r.name: r for r in pv.verify(events)}
    assert by_name["promise_action_consistency"].verdict == Verdict.PASS


# ============================================================
# quality_verifier.py
# ============================================================


def test_quality_no_judge_uncertain():
    qv = QualityVerifier(judge=None)
    results = qv.verify("t1", [])
    assert len(results) == 1
    assert results[0].verdict == Verdict.UNCERTAIN
    assert results[0].severity == Severity.LOW


def test_quality_judge_returns_valid_json():
    def judge(prompt: str) -> str:
        return json.dumps({
            "change_scope": {
                "verdict": "pass",
                "confidence": 0.9,
                "reason": "改动最小",
            }
        })

    qv = QualityVerifier(judge=judge)
    results = qv.verify("t1", [])
    assert len(results) >= 1
    assert results[0].verdict == Verdict.PASS


def test_quality_judge_returns_invalid_json():
    def judge(prompt: str) -> str:
        return "not json"

    qv = QualityVerifier(judge=judge)
    results = qv.verify("t1", [])
    assert results[0].verdict == Verdict.UNCERTAIN


def test_quality_judge_raises():
    def judge(prompt: str) -> str:
        raise RuntimeError("LLM 挂了")

    qv = QualityVerifier(judge=judge)
    results = qv.verify("t1", [])
    assert results[0].verdict == Verdict.UNCERTAIN
    assert "失败" in results[0].reason


# ============================================================
# orchestrator.py — 四态聚合
# ============================================================


def test_orchestrator_all_pass():
    events = [
        make_event(type_="tool_result", name="read_file", success=True, content="ok"),
    ]
    diag = TrajectoryVerifier().verify("t1", events)
    assert diag.overall_verdict == Verdict.PASS
    assert diag.success is True
    assert diag.veto_triggered is False


def test_orchestrator_with_fail():
    """execute 失败 → overall FAIL。"""
    events = [
        make_event(
            type_="tool_result",
            name="execute",
            success=True,
            exit_code=127,
        ),
    ]
    diag = TrajectoryVerifier().verify("t1", events)
    assert diag.overall_verdict == Verdict.FAIL
    assert diag.success is False


def test_orchestrator_veto_triggers_fail():
    """写文件但未执行 → veto → FAIL。"""
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
    ]
    diag = TrajectoryVerifier().verify("t1", events)
    assert diag.overall_verdict == Verdict.FAIL
    assert diag.veto_triggered is True


def test_orchestrator_uncertain_from_high():
    """HIGH 维度 UNCERTAIN → overall UNCERTAIN。"""
    events = [
        make_event(type_="tool_result", name="write_file", success=True),
        make_event(
            type_="tool_result",
            name="run_tests",
            success=True,
            content="测试结果: ✓ 全部通过",
        ),
    ]
    diag = TrajectoryVerifier().verify("t1", events)
    assert diag.overall_verdict in (Verdict.PASS, Verdict.UNCERTAIN)


def test_orchestrator_summary_contains_task_id():
    events = []
    diag = TrajectoryVerifier().verify("my-task", events)
    assert "my-task" in diag.summary


def test_orchestrator_custom_verifiers():
    """可注入自定义 verifier。"""
    def fake_result(events):
        return DimensionResult(name="task_result", verdict=Verdict.PASS,
                                severity=Severity.HIGH)

    v = TrajectoryVerifier(result_verifier=type(
        "Fake", (), {"verify": staticmethod(fake_result)})())
    diag = v.verify("t1", [])
    assert diag.get("task_result") is not None
