"""P4-2/P4-3: 跑单条案例。

设计要点：
  - 复用 P0 的三层验证器
  - 每条案例用独立 thread_id + rotate 到独立轨迹文件
  - flush_now 保证读文件前所有事件已落盘
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from .schema import EvalCase, EvalResult


class EvalRunner:
    def __init__(self, rt):
        self.rt = rt

    def run_one(self, case: EvalCase, timeout_s: float = 180.0) -> EvalResult:
        t0 = time.time()
        thread_id = f"eval-{case.case_id}-{uuid.uuid4().hex[:6]}"

        tw = getattr(self.rt, "trajectory_writer", None)
        if tw is None:
            return EvalResult(
                case_id=case.case_id,
                actual_verdict="uncertain",
                actual_veto=False,
                success=False,
                error="trajectory_writer 未启用（eval 模式？）",
            )

        # ---------- 1. 轮换到独立文件 ----------
        try:
            tw.rotate(f"eval-{case.case_id}")
        except Exception as e:
            return EvalResult(
                case_id=case.case_id,
                actual_verdict="uncertain",
                actual_veto=False,
                success=False,
                error=f"rotate 失败: {e}",
            )

        traj_path = Path(tw.path)

        # ---------- 2. 跑案例 ----------
        tool_calls = 0
        try:
            from langchain_core.messages import ToolMessage

            for chunk in self.rt.agent.stream(
                {"messages": [{"role": "user", "content": case.task}]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 40,
                },
                stream_mode="messages",
            ):
                msg = chunk[0] if isinstance(chunk, tuple) else chunk
                if msg is None:
                    continue
                if isinstance(msg, ToolMessage):
                    tool_calls += 1

                if time.time() - t0 > timeout_s:
                    return EvalResult(
                        case_id=case.case_id,
                        actual_verdict="uncertain",
                        actual_veto=False,
                        success=False,
                        error=f"超时 ({timeout_s}s)",
                        tool_calls=tool_calls,
                        elapsed_s=time.time() - t0,
                    )

        except Exception as e:
            return EvalResult(
                case_id=case.case_id,
                actual_verdict="uncertain",
                actual_veto=False,
                success=False,
                error=f"{type(e).__name__}: {e}",
                tool_calls=tool_calls,
                elapsed_s=time.time() - t0,
            )

        # ---------- 3. 落盘 + 解析 ----------
        try:
            tw.flush_now(timeout=3.0)
        except Exception:
            pass

        if not traj_path.exists() or traj_path.stat().st_size == 0:
            return EvalResult(
                case_id=case.case_id,
                actual_verdict="uncertain",
                actual_veto=False,
                success=False,
                error="未生成轨迹文件",
                tool_calls=tool_calls,
                elapsed_s=time.time() - t0,
            )

        try:
            from verification import TrajectoryVerifier, load_events
            from verification.schema import Verdict

            events = load_events(traj_path)
            if not events:
                return EvalResult(
                    case_id=case.case_id,
                    actual_verdict="uncertain",
                    actual_veto=False,
                    success=False,
                    error="轨迹为空",
                    tool_calls=tool_calls,
                    elapsed_s=time.time() - t0,
                )

            verifier = TrajectoryVerifier()
            diag = verifier.verify(task_id=case.case_id, events=events)

            actual_verdict = diag.overall_verdict.value
            actual_veto = diag.veto_triggered

            failed_dims = [
                d.name for d in diag.dimensions if d.verdict == Verdict.FAIL
            ]

            success = (
                actual_verdict == case.expected_verdict
                and actual_veto == case.expected_veto
            )
            diff_reason = ""
            if not success:
                diff_reason = (
                    f"期望 {case.expected_verdict}"
                    f"{'(veto)' if case.expected_veto else ''} "
                    f"实际 {actual_verdict}"
                    f"{'(veto)' if actual_veto else ''}"
                )

            return EvalResult(
                case_id=case.case_id,
                actual_verdict=actual_verdict,
                actual_veto=actual_veto,
                success=success,
                diff_reason=diff_reason,
                failed_dimensions=failed_dims,
                tool_calls=tool_calls,
                elapsed_s=time.time() - t0,
            )

        except Exception as e:
            return EvalResult(
                case_id=case.case_id,
                actual_verdict="uncertain",
                actual_veto=False,
                success=False,
                error=f"评分失败: {type(e).__name__}: {e}",
                tool_calls=tool_calls,
                elapsed_s=time.time() - t0,
            )