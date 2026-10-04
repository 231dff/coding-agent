from __future__ import annotations

from .process_verifier import ProcessVerifier
from .quality_verifier import QualityVerifier
from .result_verifier import ResultVerifier
from .schema import Severity, TrajectoryDiagnosis, Verdict


class TrajectoryVerifier:
    def __init__(
        self,
        result_verifier=None,
        process_verifier=None,
        quality_verifier=None,
    ):
        self.result_verifier = result_verifier or ResultVerifier()
        self.process_verifier = process_verifier or ProcessVerifier()
        self.quality_verifier = quality_verifier or QualityVerifier()

    def verify(self, task_id, events):
        diag = TrajectoryDiagnosis(task_id=task_id)
        diag.add(self.result_verifier.verify(events))
        for d in self.process_verifier.verify(events):
            diag.add(d)
        for d in self.quality_verifier.verify(task_id, events):
            diag.add(d)

        r = diag.get("task_result")
        diag.success = bool(r and r.verdict == Verdict.PASS and not diag.veto_triggered)

        # ★ 只有 HIGH+ 维度的 UNCERTAIN 才拖累整体
        #   quality_judge（LOW）未配置时不判 UNCERTAIN
        high_uncertain = any(
            d.verdict == Verdict.UNCERTAIN and d.severity in (Severity.HIGH, Severity.VETO)
            for d in diag.dimensions
        )

        if diag.veto_triggered:
            diag.overall_verdict = Verdict.FAIL
        elif any(d.verdict == Verdict.FAIL for d in diag.dimensions):
            diag.overall_verdict = Verdict.FAIL
        elif high_uncertain:
            diag.overall_verdict = Verdict.UNCERTAIN
        else:
            diag.overall_verdict = Verdict.PASS

        diag.summary = self._summarize(diag)
        return diag

    @staticmethod
    def _summarize(diag):
        lines = [f"任务 {diag.task_id}: {diag.overall_verdict.value} (success={diag.success})"]
        if diag.veto_triggered:
            lines.append("[VETO] 触发一票否决")
        for d in diag.dimensions:
            if d.verdict == Verdict.PASS:
                continue
            lines.append(f"- [{d.severity.value}] {d.name}: {d.reason}")
        if diag.requires_human_review:
            lines.append("-> 存在低置信度结论, 建议人工复核")
        return "\n".join(lines)
