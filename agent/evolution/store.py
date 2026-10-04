"""P2-1: 经验归档。

每次任务结束时，把诊断结果 + 审查结论 + 任务摘要归档到
.coding-agent/evolution/experiences.jsonl。

这是持续进化的证据基础——原始轨迹不可变，经验记录是提炼过的摘要。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExperienceRecord:
    """一次任务的提炼经验。"""

    ts: float
    session_id: str
    task: str
    verdict: str                       # pass / fail / uncertain
    veto_triggered: bool = False
    success: bool = False
    failed_dimensions: list[str] = field(default_factory=list)
    uncertain_dimensions: list[str] = field(default_factory=list)
    reviewer_verdict: str = ""         # approve / reject / needs_human
    reviewer_confidence: float = 0.0
    reviewer_issues: list[dict] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    tool_calls_count: int = 0
    elapsed_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class EvolutionStore:
    """经验归档存储。"""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.experiences_path = self.root / "experiences.jsonl"
        self.proposals_dir = self.root / "proposals"
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, exp: ExperienceRecord) -> None:
        line = json.dumps(asdict(exp), ensure_ascii=False)
        with self._lock:
            with self.experiences_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def load_recent(self, n: int = 50) -> list[ExperienceRecord]:
        if not self.experiences_path.exists():
            return []
        lines = self.experiences_path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in reversed(lines[-n:]):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                d.setdefault("failed_dimensions", [])
                d.setdefault("uncertain_dimensions", [])
                d.setdefault("reviewer_issues", [])
                d.setdefault("files_changed", [])
                d.setdefault("metadata", {})
                records.append(ExperienceRecord(**d))
            except (json.JSONDecodeError, TypeError):
                continue
        return records

    def save_proposal(self, content: str, name: str | None = None) -> Path:
        if name is None:
            name = f"proposal-{time.strftime('%Y%m%d-%H%M%S')}"
        path = self.proposals_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        return path


_STORE: EvolutionStore | None = None
_STORE_LOCK = threading.Lock()


def get_store(root: Path | str | None = None) -> EvolutionStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            if root is None:
                root = Path.home() / ".coding-agent" / "evolution"
            _STORE = EvolutionStore(root)
        return _STORE


def set_store(store: EvolutionStore) -> None:
    global _STORE
    _STORE = store
