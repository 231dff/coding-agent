"""第 3 步功能：摘要聚合器单元测试。

覆盖：
  - _format_summaries：格式化
  - _parse_json：容错 JSON 解析
  - _extract_content：多形态响应提取
  - _aggregate_one_group：单组聚合（mock LLM）
  - aggregate_summaries：主流程（阈值 / 分组 / 标记 / 异常）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from memory.session_summary import (
    SessionSummary,
    SessionSummaryRepository,
)
from memory.summary_aggregator import (
    _aggregate_one_group,
    _extract_content,
    _format_summaries,
    _parse_json,
    aggregate_summaries,
)

# ============================================================
# fixtures
# ============================================================


class FakeLLM:
    """极简 LLM stub：按预设序列返回 content，或抛异常。"""

    def __init__(self, responses):
        # responses: list[str | Exception]
        self.responses = list(responses)
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        if not self.responses:
            return SimpleNamespace(content="{}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=item)


@pytest.fixture
def store():
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


@pytest.fixture
def repo(store):
    return SessionSummaryRepository(store, user_id="test")


def _make_summary(sid: str, task_type: str = "implement", **kwargs) -> SessionSummary:
    defaults = dict(
        session_id=sid,
        summary=f"摘要 {sid}",
        task_type=task_type,
        key_facts=[f"事实 {sid}"],
        level="raw",
    )
    defaults.update(kwargs)
    return SessionSummary(**defaults)


# ============================================================
# _format_summaries
# ============================================================


def test_format_summaries_basic():
    items = [
        _make_summary("a"),
        _make_summary("b"),
    ]
    text = _format_summaries(items)
    assert "[1]" in text
    assert "[2]" in text
    assert "摘要 a" in text
    assert "事实 a" in text


def test_format_summaries_no_key_facts():
    items = [_make_summary("x", key_facts=[])]
    text = _format_summaries(items)
    assert "事实" not in text
    assert "摘要 x" in text


# ============================================================
# _parse_json
# ============================================================


def test_parse_json_direct():
    raw = '{"summary": "x", "key_facts": ["a"], "has_pattern": true}'
    result = _parse_json(raw)
    assert result["summary"] == "x"


def test_parse_json_markdown_wrapped():
    raw = '```json\n{"summary": "y"}\n```'
    result = _parse_json(raw)
    assert result["summary"] == "y"


def test_parse_json_with_prefix_text():
    """LLM 有时会在 JSON 前后加自然语言。"""
    raw = '这是我的合并结果：\n{"summary": "z"}\n希望有帮助。'
    result = _parse_json(raw)
    assert result["summary"] == "z"


def test_parse_json_invalid_returns_none():
    result = _parse_json("这不是 JSON")
    assert result is None


def test_parse_json_array_returns_none():
    """数组不是 dict → None（我们只要 dict）。"""
    result = _parse_json("[1, 2, 3]")
    assert result is None


# ============================================================
# _extract_content
# ============================================================


def test_extract_content_str():
    resp = SimpleNamespace(content="hello")
    assert _extract_content(resp) == "hello"


def test_extract_content_list_of_blocks():
    resp = SimpleNamespace(content=[
        {"type": "text", "text": "part1"},
        {"type": "text", "text": "part2"},
    ])
    assert _extract_content(resp) == "part1part2"


def test_extract_content_list_mixed():
    resp = SimpleNamespace(content=["raw str", {"type": "text", "text": "boxed"}])
    assert _extract_content(resp) == "raw strboxed"


def test_extract_content_none():
    resp = SimpleNamespace(content=None)
    assert _extract_content(resp) == "None"


# ============================================================
# _aggregate_one_group（mock LLM）
# ============================================================


def test_aggregate_one_group_success():
    llm = FakeLLM([
        json.dumps({
            "summary": "合并结果",
            "key_facts": ["通用事实"],
            "has_pattern": True,
        })
    ])
    items = [_make_summary("a"), _make_summary("b")]

    result = _aggregate_one_group(llm, "implement", items)
    assert result["summary"] == "合并结果"
    assert result["key_facts"] == ["通用事实"]
    assert result["has_pattern"] is True


def test_aggregate_one_group_llm_raises():
    llm = FakeLLM([RuntimeError("LLM 挂了")])
    items = [_make_summary("a")]
    result = _aggregate_one_group(llm, "implement", items)
    assert result is None


def test_aggregate_one_group_invalid_json():
    llm = FakeLLM(["完全不是 JSON"])
    items = [_make_summary("a")]
    result = _aggregate_one_group(llm, "implement", items)
    assert result is None


def test_aggregate_one_group_empty_summary():
    """返回的 summary 为空字符串 → 视为失败。"""
    llm = FakeLLM([json.dumps({"summary": "", "key_facts": []})])
    items = [_make_summary("a")]
    result = _aggregate_one_group(llm, "implement", items)
    assert result is None


def test_aggregate_one_group_summary_truncated():
    """超长 summary 被截断到 500 字。"""
    long_text = "x" * 1000
    llm = FakeLLM([json.dumps({"summary": long_text, "key_facts": []})])
    items = [_make_summary("a")]
    result = _aggregate_one_group(llm, "implement", items)
    assert len(result["summary"]) == 500


# ============================================================
# aggregate_summaries — 主流程
# ============================================================


def test_aggregate_below_threshold(repo):
    """raw 不够阈值 → 不聚合，返回 0。"""
    for i in range(3):
        repo.add(_make_summary(f"s{i}"))

    llm = FakeLLM([])
    result = aggregate_summaries(llm, repo, threshold=10)

    assert result["aggregated"] == 0
    assert result["created"] == 0
    assert len(llm.calls) == 0  # 没调 LLM


def test_aggregate_single_group(repo):
    """一组 >= min_group_size 的 raw → 生成 1 条 daily。"""
    for i in range(5):
        repo.add(_make_summary(f"s{i}", task_type="implement"))

    llm = FakeLLM([json.dumps({
        "summary": "合并摘要",
        "key_facts": ["统一事实"],
        "has_pattern": True,
    })])

    result = aggregate_summaries(llm, repo, threshold=3, min_group_size=2)
    assert result["created"] == 1
    assert result["aggregated"] == 5

    all_s = repo.load_all()
    dailies = [s for s in all_s if s.level == "daily"]
    assert len(dailies) == 1
    assert dailies[0].summary == "合并摘要"
    assert len(dailies[0].source_ids) == 5


def test_aggregate_marks_source_aggregated(repo):
    """被聚合的 raw 打上 aggregated_into。"""
    for i in range(3):
        repo.add(_make_summary(f"s{i}"))

    llm = FakeLLM([json.dumps({"summary": "x", "has_pattern": True})])
    aggregate_summaries(llm, repo, threshold=2, min_group_size=2)

    all_s = repo.load_all()
    raws = [s for s in all_s if s.level == "raw"]
    assert all(r.aggregated_into for r in raws)  # 全部已标记


def test_aggregate_two_groups(repo):
    """两个 task_type → 生成 2 条 daily。"""
    for i in range(3):
        repo.add(_make_summary(f"impl{i}", task_type="implement"))
    for i in range(3):
        repo.add(_make_summary(f"bug{i}", task_type="debug"))

    llm = FakeLLM([
        json.dumps({"summary": "implement 汇总", "has_pattern": True}),
        json.dumps({"summary": "debug 汇总", "has_pattern": True}),
    ])

    result = aggregate_summaries(llm, repo, threshold=5, min_group_size=2)
    assert result["created"] == 2
    assert result["aggregated"] == 6


def test_aggregate_group_too_small(repo):
    """单条 raw 的组不聚合（min_group_size=2）。"""
    repo.add(_make_summary("s1", task_type="implement"))
    repo.add(_make_summary("s2", task_type="debug"))
    repo.add(_make_summary("s3", task_type="explain"))

    llm = FakeLLM([])
    result = aggregate_summaries(llm, repo, threshold=2, min_group_size=2)
    assert result["created"] == 0


def test_aggregate_max_groups_limit(repo):
    """max_groups_per_run 限制单次处理的组数。"""
    for tt in ("a", "b", "c", "d", "e"):
        for i in range(2):
            repo.add(_make_summary(f"{tt}{i}", task_type=tt))

    llm = FakeLLM([
        json.dumps({"summary": f"sum-{i}", "has_pattern": True})
        for i in range(2)
    ])

    result = aggregate_summaries(
        llm, repo, threshold=5, min_group_size=2, max_groups_per_run=2
    )
    assert result["created"] == 2  # 只处理 2 组


def test_aggregate_skips_group_on_llm_failure(repo):
    """一个组 LLM 失败，其余组继续。"""
    for i in range(2):
        repo.add(_make_summary(f"a{i}", task_type="aaa"))
    for i in range(2):
        repo.add(_make_summary(f"b{i}", task_type="bbb"))

    llm = FakeLLM([
        RuntimeError("第一组挂了"),
        json.dumps({"summary": "bbb 成功", "has_pattern": True}),
    ])

    result = aggregate_summaries(llm, repo, threshold=3, min_group_size=2)
    assert result["created"] == 1
    assert result["skipped_groups"] == 1


def test_aggregate_no_unaggregated(repo):
    """所有 raw 都已聚合 → 返回 0。"""
    s = _make_summary("s1", aggregated_into="parent-id")
    repo.add(s)
    s2 = _make_summary("s2", aggregated_into="parent-id")
    repo.add(s2)

    llm = FakeLLM([])
    result = aggregate_summaries(llm, repo, threshold=1, min_group_size=1)
    assert result["created"] == 0
