"""Day 9: 依赖图测试。"""

import pytest

from codebase.dep_graph import DependencyGraph
from codebase.parser import CodeParser


@pytest.fixture
def dep_project(tmp_path):
    (tmp_path / "a.py").write_text("from b import foo\n\ndef bar():\n    return foo()\n")
    (tmp_path / "b.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "c.py").write_text("from a import bar\n\ndef baz():\n    return bar()\n")
    return tmp_path


def test_build_graph(dep_project):
    parser = CodeParser(dep_project)
    graph = DependencyGraph(parser)
    graph.build()
    assert "a.py" in graph.graph
    assert "b.py" in graph.graph


def test_dependents(dep_project):
    parser = CodeParser(dep_project)
    graph = DependencyGraph(parser)
    graph.build()
    deps = graph.dependents("b.py")
    assert "a.py" in deps


def test_dependencies(dep_project):
    parser = CodeParser(dep_project)
    graph = DependencyGraph(parser)
    graph.build()
    deps = graph.dependencies("a.py")
    assert "b.py" in deps


def test_transitive_dependents(dep_project):
    parser = CodeParser(dep_project)
    graph = DependencyGraph(parser)
    graph.build()
    deps = graph.dependents("b.py", depth=2)
    assert "c.py" in deps


def test_no_cycles(dep_project):
    parser = CodeParser(dep_project)
    graph = DependencyGraph(parser)
    graph.build()
    assert graph.find_cycles() == []
