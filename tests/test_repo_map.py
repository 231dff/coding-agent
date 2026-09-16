"""Day 7: Repo Map 测试。"""
import pytest
from codebase.parser import CodeParser
from codebase.repo_map import RepoMapBuilder


@pytest.fixture
def map_project(tmp_path):
    for i in range(5):
        (tmp_path / f"mod{i}.py").write_text(
            f"def func_{i}():\n    return {i}\n"
        )
    return tmp_path


def test_repo_map_generates(map_project):
    parser = CodeParser(map_project)
    builder = RepoMapBuilder(parser)
    text = builder.build(token_budget=500)
    assert "func_0" in text or "func_1" in text


def test_repo_map_respects_budget(map_project):
    parser = CodeParser(map_project)
    builder = RepoMapBuilder(parser)
    text = builder.build(token_budget=100)
    # 粗略估算 token
    assert len(text) / 4 <= 150  # 允许一定误差