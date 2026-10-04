"""解析 TrajectoryWriter 的轨迹文件。

支持两种格式：
  新（middleware/trajectory.py 当前输出）:
    {"event": "tool_call", "ts": ..., "name": ..., "args": {...}}
    {"event": "tool_result", "ts": ..., "name": ..., "success": true, "output": "..."}
  旧（历史文件）:
    {"ts": ..., "type": "tool_call", "data": {"name": ..., "args": {...}}}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_OUTPUT_RE = re.compile(
    r"^content='(?P<content>.*)'\s+name='(?P<name>[^']*)'\s+tool_call_id='(?P<cid>[^']*)'$",
    re.DOTALL,
)
_EXIT_RE = re.compile(r"EXIT:\s*(\d+)")
_OCI_ERR_RE = re.compile(r"OCI runtime exec failed")


@dataclass
class TrajEvent:
    line_no: int
    ts: float
    type: str
    name: str | None
    args: dict | None
    success: bool | None
    output_raw: str | None
    content: str | None
    tool_call_id: str | None
    exit_code: int | None
    has_oci_error: bool
    raw: dict


def iter_events(path) -> Iterator[TrajEvent]:
    with Path(path).open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield _parse(i, json.loads(line))
            except json.JSONDecodeError:
                continue


def _parse(line_no: int, rec: dict) -> TrajEvent:
    ts = float(rec.get("ts", 0.0))

    # ★ 兼容两种格式
    if "data" in rec:
        # 旧格式：{"ts": ..., "type": ..., "data": {...}}
        etype = rec.get("type", "")
        data = rec.get("data", {}) or {}
    else:
        # 新格式：{"event": ..., "ts": ..., "name": ..., "args": ...}
        etype = rec.get("event", "")
        data = rec  # 字段在顶层

    name = data.get("name")
    args = data.get("args")
    success = data.get("success")

    # output 优先，缺失时回退到 error
    output_raw = data.get("output") or data.get("error")

    content = None
    tool_call_id = None
    if isinstance(output_raw, str):
        m = _OUTPUT_RE.match(output_raw)
        if m:
            content = m.group("content")
            tool_call_id = m.group("cid")
            if name is None:
                name = m.group("name")
        else:
            cid_m = re.search(r"tool_call_id='([^']+)'", output_raw)
            if cid_m:
                tool_call_id = cid_m.group(1)
            content = output_raw

    exit_code = None
    if isinstance(output_raw, str):
        em = _EXIT_RE.search(output_raw)
        if em:
            exit_code = int(em.group(1))

    has_oci_error = bool(
        isinstance(output_raw, str) and _OCI_ERR_RE.search(output_raw)
    )

    return TrajEvent(
        line_no=line_no, ts=ts, type=etype, name=name, args=args,
        success=success, output_raw=output_raw, content=content,
        tool_call_id=tool_call_id, exit_code=exit_code,
        has_oci_error=has_oci_error, raw=rec,
    )


def load_events(path):
    return list(iter_events(path))

def parse_lines(lines) -> list[TrajEvent]:
    """从字符串行序列解析事件。

    用于「读文件某个字节位置之后的增量内容」这类场景。
    line_no 是相对新片段的索引，不影响解析逻辑。
    """
    events = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(_parse(i, json.loads(line)))
        except json.JSONDecodeError:
            continue
    return events