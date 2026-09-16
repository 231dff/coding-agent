"""Day 14: 依赖检查中间件测试。"""

import pytest

from codebase.call_graph import CallGraph
from codebase.dep_graph import DependencyGraph
from codebase.impact import ImpactAnalyzer
from codebase.parser import CodeParser
from middleware.dependency_check import DependencyCheckMiddleware


@pytest.fixture
def analyzer(tmp_path):
    (tmp_path / "service.py").write_text(
        "def process(data):\n    return validate(data)\n\n"
        "def validate(data):\n    return data is not None\n"
    )
    (tmp_path / "api.py").write_text(
        "from service import process\n\ndef handler(req):\n    return process(req)\n"
    )
    parser = CodeParser(tmp_path)
    dep = DependencyGraph(parser)
    dep.build()
    cg = CallGraph(parser)
    cg.build()
    return ImpactAnalyzer(cg, dep)


def test_extract_symbols_from_edit(analyzer):
    mw = DependencyCheckMiddleware(analyzer)
    args = {
        "path": "service.py",
        "old_string": "def validate(data):\n    return data is not None\n",
        "new_string": "def validate(data):\n    return bool(data)\n",
    }
    impacts = mw._extract_and_analyze(args)
    assert "validate" in impacts


def test_format_hint_includes_affected(analyzer):
    mw = DependencyCheckMiddleware(analyzer)
    report = analyzer.analyze("validate")
    hint = mw._format_hint({"validate": report})
    assert "validate" in hint
    assert "service.py" in hint or "api.py" in hint
