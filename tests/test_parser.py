"""Day 6: 解析器单元测试。"""

import pytest

from codebase.parser import CodeParser


@pytest.fixture
def project(tmp_path):
    (tmp_path / "main.py").write_text(
        "import os\n"
        "from utils import helper\n"
        "\n"
        "CONSTANT = 42\n"
        "\n"
        "def main():\n"
        "    result = helper()\n"
        "    return result\n"
        "\n"
        "class App:\n"
        "    def run(self):\n"
        "        return main()\n"
    )
    (tmp_path / "utils.py").write_text("def helper():\n    return 'ok'\n")
    return tmp_path


def test_parse_file_extracts_symbols(project):
    parser = CodeParser(project)
    parsed = parser.parse_file(project / "main.py")
    assert parsed is not None
    names = {s.name for s in parsed.symbols}
    assert "main" in names
    assert "App" in names
    assert "run" in names
    assert "CONSTANT" in names


def test_parse_file_signatures(project):
    parser = CodeParser(project)
    parsed = parser.parse_file(project / "main.py")
    main_sym = next(s for s in parsed.symbols if s.name == "main")
    assert "def main()" in main_sym.signature


def test_incremental_parse(project):
    parser = CodeParser(project)
    p1 = parser.parse_file(project / "main.py")
    p2 = parser.parse_file(project / "main.py")
    assert p1 is p2  # 缓存命中


def test_parse_all(project):
    parser = CodeParser(project)
    files = parser.parse_all()
    assert len(files) == 2


def test_ignore_venv(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("x = 1")
    (tmp_path / "main.py").write_text("y = 2")
    parser = CodeParser(tmp_path)
    files = parser.parse_all()
    assert len(files) == 1
    assert files[0].path == "main.py"
