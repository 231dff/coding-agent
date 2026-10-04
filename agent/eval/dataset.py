"""P4-2: 从历史经验里挖案例 + 存/读案例库。"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from .schema import EvalCase


class EvalDataset:
    """案例库：读写 .coding-agent/eval/cases.jsonl。"""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cases_path = self.root / "cases.jsonl"

    def load(self) -> list[EvalCase]:
        if not self.cases_path.exists():
            return []
        cases = []
        for line in self.cases_path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                cases.append(EvalCase(**d))
            except (json.JSONDecodeError, TypeError):
                continue
        return cases

    def save(self, cases: list[EvalCase]) -> None:
        lines = [json.dumps(c.__dict__, ensure_ascii=False) for c in cases]
        self.cases_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def append(self, case: EvalCase) -> None:
        with self.cases_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(case.__dict__, ensure_ascii=False) + "\n")

    def get(self, case_id: str) -> EvalCase | None:
        for c in self.load():
            if c.case_id == case_id:
                return c
        return None


def mine_cases(
    experiences_path: Path | str,
    dataset: EvalDataset,
    n: int = 20,
    seed: int = 42,
    max_per_category: int = 8,
) -> list[EvalCase]:
    """从 experiences.jsonl 挖案例。

    策略：
      - 优先选 verdict=fail / veto 的（这些是最重要的回归保护）
      - 成功的也留一些（确保基础能力不退化）
      - 按 category 分组，每类最多 max_per_category 条
    """
    experiences_path = Path(experiences_path)
    if not experiences_path.exists():
        return []

    raw = []
    for line in experiences_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        try:
            raw.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not raw:
        return []

    # 分类
    buckets: dict[str, list[dict]] = {
        "veto": [],
        "failure": [],
        "pass": [],
        "uncertain": [],
    }
    for e in raw:
        verdict = e.get("verdict", "uncertain")
        if e.get("veto_triggered"):
            buckets["veto"].append(e)
        elif verdict == "fail":
            buckets["failure"].append(e)
        elif verdict == "pass":
            buckets["pass"].append(e)
        else:
            buckets["uncertain"].append(e)

    # 每类采样
    random.seed(seed)
    picked: list[dict] = []
    for cat, items in buckets.items():
        random.shuffle(items)
        picked.extend(items[:max_per_category])

    random.shuffle(picked)
    picked = picked[:n]

    # 转成 EvalCase
    cases = []
    for i, e in enumerate(picked):
        category = (
            "veto" if e.get("veto_triggered")
            else "failure" if e.get("verdict") == "fail"
            else "general"
        )
        case_id = f"case-{int(time.time())}-{i:03d}"
        cases.append(EvalCase(
            case_id=case_id,
            task=e.get("task", "")[:500],
            category=category,
            expected_verdict=e.get("verdict", "uncertain"),
            expected_veto=bool(e.get("veto_triggered")),
            baseline_verdict=e.get("verdict", ""),
            baseline_session=e.get("session_id", ""),
            notes=f"来自会话 {e.get('session_id', '?')}",
        ))

    dataset.save(cases)
    return cases
