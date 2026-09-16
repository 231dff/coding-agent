"""Day 10: 调用图与影响分析测试。"""
import pytest
from codebase.parser import CodeParser
from codebase.dep_graph import DependencyGraph
from codebase.call_graph import CallGraph
from codebase.impact import ImpactAnalyzer


@pytest.fixture
def call_project(tmp_path):
    (tmp_path / "service.py").write_text(
        "def process(data):\n"
        "    return validate(data)\n"
        "\n"
        "def validate(data):\n"
        "    return data is not None\n"
    )
    (tmp_path / "api.py").write_text(
        "from service import process\n"
        "\n"
        "def handler(request):\n"
        "    return process(request)\n"
    )
    return tmp_path


def test_call_graph_builds(call_project):
    parser = CodeParser(call_project)
    cg = CallGraph(parser)
    cg.build()
    assert len(cg.graph.nodes()) > 0


def test_find_callers(call_project):
    parser = CodeParser(call_project)
    cg = CallGraph(parser)
    cg.build()
    callers = cg.callers_of("process")
    assert any("handler" in c for c in callers)


def test_impact_analysis(call_project):
    parser = CodeParser(call_project)
    dep = DependencyGraph(parser)
    dep.build()
    cg = CallGraph(parser)
    cg.build()
    analyzer = ImpactAnalyzer(cg, dep)
    report = analyzer.analyze("validate")
    assert report.definition
    assert len(report.affected_files) > 0