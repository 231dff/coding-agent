"""Day 21: 技能测试。"""

import pytest

from skills.registry import SkillRegistry


@pytest.fixture
def registry(tmp_path):
    d = tmp_path / "definitions"
    d.mkdir()
    (d / "test_skill.md").write_text(
        "---\n"
        "name: test_skill\n"
        "description: 测试技能\n"
        "trigger: 当需要测试时\n"
        "tools: execute, sandbox_read\n"
        "---\n"
        "# 测试内容\n\n这是技能正文。\n"
    )
    return SkillRegistry(d)


def test_registry_loads_skill(registry):
    skill = registry.get("test_skill")
    assert skill is not None
    assert skill.description == "测试技能"
    assert "execute" in skill.tools


def test_metadata_prompt(registry):
    prompt = registry.metadata_prompt()
    assert "test_skill" in prompt
    assert "测试技能" in prompt
    # 不应包含完整内容
    assert "这是技能正文" not in prompt


def test_load_skill_content(registry):
    skill = registry.get("test_skill")
    content = skill.load()
    assert "这是技能正文" in content


def test_unknown_skill(registry):
    assert registry.get("nonexistent") is None
