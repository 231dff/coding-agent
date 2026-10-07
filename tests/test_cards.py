"""Day X: 用户卡片（Cards）单元测试。

覆盖：
  - Card 数据类：自动 id、时间戳、向后兼容、prompt 行格式
  - priority_score：时间衰减、命中加权、复合分
  - CardRepository：增删改查、load_active 过滤、mark_hit、render_prompt
"""

from __future__ import annotations

import time

import pytest

from memory.cards import (
    _TTL_HALFLIFE_DAYS,
    Card,
    CardRepository,
)

# ============================================================
# fixtures
# ============================================================


@pytest.fixture
def store():
    """每个测试一个独立的内存 store。"""
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()


@pytest.fixture
def repo(store):
    """基于内存 store 的 CardRepository。"""
    return CardRepository(store, user_id="test")


# ============================================================
# Card 数据类
# ============================================================


def test_card_auto_id():
    """无 id 时自动生成，格式为 card-<ts>-<hex>。"""
    c = Card(fact="用户偏好简洁回答")
    assert c.id.startswith("card-")
    assert len(c.id) > 10


def test_card_auto_timestamps():
    """created_at 和 updated_at 都自动填。"""
    before = time.time()
    c = Card(fact="用户偏好简洁回答")
    after = time.time()
    assert before <= c.created_at <= after
    assert c.updated_at == c.created_at


def test_card_explicit_fields():
    """显式传入的字段不被覆盖。"""
    c = Card(
        fact="x",
        id="card-fixed-000",
        created_at=1000.0,
        updated_at=2000.0,
    )
    assert c.id == "card-fixed-000"
    assert c.created_at == 1000.0
    assert c.updated_at == 2000.0


def test_card_from_dict_backward_compat():
    """旧卡片（缺 last_hit_at / hit_count）能正常反序列化。"""
    old_dict = {
        "fact": "用户是素食者",
        "type": "preference",
        "category": "diet",
        "confidence": 0.9,
        "created_at": 1000.0,
        "id": "card-old-001",
        # 故意不提供 last_hit_at / hit_count
    }
    c = Card.from_dict(old_dict)
    assert c.fact == "用户是素食者"
    assert c.last_hit_at == 0.0
    assert c.hit_count == 0


def test_card_from_dict_ignores_unknown_keys():
    """dict 里的多余字段被忽略，不报错。"""
    weird = {
        "fact": "x",
        "unknown_field_1": "y",
        "unknown_field_2": 42,
    }
    c = Card.from_dict(weird)
    assert c.fact == "x"


def test_card_to_prompt_line():
    """prompt 行格式：[category] fact。"""
    c = Card(fact="用户偏好简洁回答", category="code_style")
    assert c.to_prompt_line() == "- [code_style] 用户偏好简洁回答"


def test_card_to_dict_roundtrip():
    """to_dict → from_dict 保持不变。"""
    original = Card(
        fact="x",
        category="code_style",
        confidence=0.85,
        hit_count=3,
        last_hit_at=1234.5,
    )
    restored = Card.from_dict(original.to_dict())
    assert restored.fact == original.fact
    assert restored.confidence == original.confidence
    assert restored.hit_count == original.hit_count
    assert restored.last_hit_at == original.last_hit_at


# ============================================================
# priority_score
# ============================================================


def test_priority_score_new_card():
    """全新卡片：confidence=1.0, hit=0, 刚创建 → ≈ 1.0。"""
    now = time.time()
    c = Card(fact="x", confidence=1.0, created_at=now, hit_count=0)
    score = c.priority_score(now)
    assert score == pytest.approx(1.0, abs=0.01)


def test_priority_score_decays_after_90_days():
    """90 天后时间衰减系数 = 0.5。"""
    now = time.time()
    c = Card(
        fact="x",
        confidence=1.0,
        created_at=now - _TTL_HALFLIFE_DAYS * 86400,
        hit_count=0,
    )
    score = c.priority_score(now)
    # 1.0 * 0.5 + 0 = 0.5
    assert score == pytest.approx(0.5, abs=0.02)


def test_priority_score_hit_boost():
    """hit_count 越大，分数越高。"""
    now = time.time()
    no_hit = Card(fact="x", confidence=1.0, created_at=now, hit_count=0)
    many_hits = Card(fact="x", confidence=1.0, created_at=now, hit_count=20)

    assert many_hits.priority_score(now) > no_hit.priority_score(now)
    # 20 次命中时，hit_boost ≈ log(21)/3 ≈ 1.015，贡献 ≈ 0.30
    assert many_hits.priority_score(now) >= 1.2


def test_priority_score_monotonic_with_confidence():
    """其他条件相同时，confidence 越高分越高。"""
    now = time.time()
    low = Card(fact="x", confidence=0.5, created_at=now, hit_count=0)
    high = Card(fact="x", confidence=0.9, created_at=now, hit_count=0)
    assert high.priority_score(now) > low.priority_score(now)


# ============================================================
# CardRepository — CRUD
# ============================================================


def test_repo_add_and_get(repo):
    """add 后能用 get 取回。"""
    c = Card(fact="用户偏好简洁回答", confidence=0.9)
    repo.add(c)
    got = repo.get(c.id)
    assert got is not None
    assert got.fact == "用户偏好简洁回答"


def test_repo_get_nonexistent(repo):
    """查不存在的 id 返回 None。"""
    assert repo.get("card-does-not-exist") is None


def test_repo_load_active(repo):
    """load_active 返回添加的所有卡片。"""
    repo.add(Card(fact="a"))
    repo.add(Card(fact="b"))
    repo.add(Card(fact="c"))
    assert len(repo.load_active()) == 3


def test_repo_load_active_excludes_deleted(repo):
    """delete 后卡片不再出现在 load_active。"""
    c = Card(fact="待删除")
    repo.add(c)
    assert len(repo.load_active()) == 1

    repo.delete(c.id)
    assert len(repo.load_active()) == 0


def test_repo_delete_creates_tombstone(repo):
    """delete 写入 tombstone（type=deleted）。"""
    c = Card(fact="x")
    repo.add(c)
    tombstone = repo.delete(c.id)

    assert tombstone.type == "deleted"
    assert tombstone.supersedes == c.id
    # tombstone 自身不出现在 load_active
    assert all(card.type != "deleted" for card in repo.load_active())


def test_repo_update_preserves_hit_history(repo):
    """update 时 last_hit_at / hit_count 从旧卡继承。"""
    old = Card(fact="旧事实", confidence=0.8)
    repo.add(old)

    # 模拟旧卡被命中过
    repo.mark_hit([old.id])

    # 更新
    new = repo.update(old.id, new_fact="新事实")

    assert new.fact == "新事实"
    assert new.version == old.version + 1
    assert new.supersedes == old.id
    # 命中历史保留
    assert new.hit_count == 1
    assert new.last_hit_at > 0


def test_repo_update_missing_raises(repo):
    """更新不存在的卡片报错。"""
    with pytest.raises(ValueError):
        repo.update("card-nonexistent", new_fact="x")


def test_repo_load_active_after_update(repo):
    """update 后 load_active 只返回新版本。"""
    old = Card(fact="旧")
    repo.add(old)
    repo.update(old.id, new_fact="新")

    active = repo.load_active()
    assert len(active) == 1
    assert active[0].fact == "新"


# ============================================================
# CardRepository — mark_hit
# ============================================================


def test_mark_hit_updates_target_only(repo):
    """mark_hit 只更新指定 ID 的卡片。"""
    c1 = Card(fact="a")
    c2 = Card(fact="b")
    repo.add(c1)
    repo.add(c2)

    n = repo.mark_hit([c1.id])
    assert n == 1

    c1_after = repo.get(c1.id)
    c2_after = repo.get(c2.id)

    assert c1_after.hit_count == 1
    assert c1_after.last_hit_at > 0
    assert c2_after.hit_count == 0
    assert c2_after.last_hit_at == 0.0


def test_mark_hit_increments_on_repeated_calls(repo):
    """多次 mark_hit 累加 hit_count。"""
    c = Card(fact="x")
    repo.add(c)

    repo.mark_hit([c.id])
    repo.mark_hit([c.id])
    repo.mark_hit([c.id])

    assert repo.get(c.id).hit_count == 3


def test_mark_hit_empty_list(repo):
    """空列表返回 0，不报错。"""
    assert repo.mark_hit([]) == 0


def test_mark_hit_unknown_id(repo):
    """未知 ID 静默跳过，返回更新数。"""
    c = Card(fact="x")
    repo.add(c)

    n = repo.mark_hit(["card-unknown-1", c.id, "card-unknown-2"])
    assert n == 1
    assert repo.get(c.id).hit_count == 1


# ============================================================
# CardRepository — render_prompt
# ============================================================


def test_render_prompt_empty(repo):
    """无卡片时返回空字符串。"""
    assert repo.render_prompt() == ""


def test_render_prompt_orders_by_priority(repo):
    """按 priority_score 从高到低排序（同 created_at 时按 confidence）。"""
    now = time.time()
    repo.add(Card(fact="低分", confidence=0.5, created_at=now))
    repo.add(Card(fact="中分", confidence=0.7, created_at=now))
    repo.add(Card(fact="高分", confidence=0.95, created_at=now))

    text = repo.render_prompt(max_cards=2)

    # 高分和中分应在，低分被截断
    assert "高分" in text
    assert "中分" in text
    assert "低分" not in text


def test_render_prompt_respects_max_cards(repo):
    """max_cards 生效。"""
    for i in range(10):
        repo.add(Card(fact=f"卡{i}", confidence=0.9))

    text = repo.render_prompt(max_cards=3)
    # 统计 "- [category]" 开头的行数
    lines = [l for l in text.splitlines() if l.startswith("- [")]
    assert len(lines) == 3


def test_render_prompt_filters_low_confidence(repo):
    """低于 min_confidence 的不渲染。"""
    repo.add(Card(fact="高分", confidence=0.9))
    repo.add(Card(fact="低分", confidence=0.3))

    text = repo.render_prompt(min_confidence=0.5)
    assert "高分" in text
    assert "低分" not in text


def test_render_prompt_mark_hit_side_effect(repo):
    """mark_hit=True 时，实际渲染的卡片被标记命中。"""
    repo.add(Card(fact="a", confidence=0.9))
    repo.add(Card(fact="b", confidence=0.9))
    repo.add(Card(fact="c", confidence=0.9))

    repo.render_prompt(max_cards=2, mark_hit=True)

    # 有 2 张卡被命中
    hit_cards = [c for c in repo.load_active() if c.hit_count > 0]
    assert len(hit_cards) == 2

    # 第三张没被命中
    untouched = [c for c in repo.load_active() if c.hit_count == 0]
    assert len(untouched) == 1


def test_render_prompt_no_mark_hit_by_default(repo):
    """默认不标记命中（不改变状态）。"""
    repo.add(Card(fact="a", confidence=0.9))
    repo.render_prompt(max_cards=5)

    assert all(c.hit_count == 0 for c in repo.load_active())


def test_render_prompt_grouped_by_category(repo):
    """按 category 分组渲染（## 标题）。"""
    repo.add(Card(fact="a", category="code_style", confidence=0.9))
    repo.add(Card(fact="b", category="tool_choice", confidence=0.9))

    text = repo.render_prompt()
    assert "## code_style" in text
    assert "## tool_choice" in text


# ============================================================
# 补充：覆盖率缺口
# ============================================================


def test_repo_find_by_category(repo):
    """按 category 过滤。"""
    repo.add(Card(fact="a", category="code_style"))
    repo.add(Card(fact="b", category="code_style"))
    repo.add(Card(fact="c", category="tool_choice"))

    result = repo.find_by_category("code_style")
    assert len(result) == 2
    assert all(c.category == "code_style" for c in result)


def test_repo_find_by_type(repo):
    """按 type 过滤。"""
    repo.add(Card(fact="a", type="preference"))
    repo.add(Card(fact="b", type="fact"))
    repo.add(Card(fact="c", type="preference"))

    result = repo.find_by_type("preference")
    assert len(result) == 2


def test_repo_load_all_versions_includes_superseded(repo):
    """load_all_versions 保留历史版本，load_active 不保留。"""
    old = Card(fact="旧")
    repo.add(old)
    repo.update(old.id, new_fact="新")

    assert len(repo.load_all_versions()) == 2  # 新旧都在
    assert len(repo.load_active()) == 1  # 只有新的


def test_repo_search_returns_list(repo):
    """search 至少能返回 list（不依赖 Store 语义）。"""
    repo.add(Card(fact="用户偏好简洁回答", category="code_style"))
    result = repo.search("用户偏好", limit=5)
    assert isinstance(result, list)


def test_user_card_repo_factory():
    """工厂函数返回 CardRepository，默认 user。"""
    from memory.cards import user_card_repo

    r = user_card_repo(user_id="test-factory")
    assert isinstance(r, CardRepository)
    assert r.user_id == "test-factory"
