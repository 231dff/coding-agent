"""file_ops 忽略目录测试。

不依赖 conftest fixture，每个测试内部自建 tmp_path。
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _build_workspace(tmp_path: Path) -> Path:
    """构造测试项目，并绑定到 file_ops。"""
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (tmp_path / "src" / "utils.py").write_text("def util():\n    return 42\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("# should be ignored\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("// should be ignored\n", encoding="utf-8")

    import tools.file_ops as file_ops

    file_ops.bind(str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    import tools.file_ops as file_ops

    file_ops._WORKSPACE = None
    file_ops._READ_CACHE.clear()


def test_glob_ignores_venv(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import glob_files

    result = glob_files.invoke({"pattern": "**/*.py"})
    assert "main.py" in result
    assert "utils.py" in result
    assert "lib.py" not in result, f"不应返回 .venv 里的文件，实际: {result}"


def test_glob_ignores_node_modules(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import glob_files

    result = glob_files.invoke({"pattern": "**/*.js"})
    assert "pkg.js" not in result, f"不应返回 node_modules 里的文件: {result}"


def test_glob_finds_normal_files(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import glob_files

    result = glob_files.invoke({"pattern": "**/*.py"})
    assert "main.py" in result
    assert "utils.py" in result


def test_glob_no_match(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import glob_files

    result = glob_files.invoke({"pattern": "**/*.rs"})
    assert "未找到" in result


def test_ls_dir_hides_ignore_dirs(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import ls_dir

    result = ls_dir.invoke({"path": "."})
    assert "src" in result
    assert "README.md" in result
    assert ".venv" not in result
    assert "node_modules" not in result


def test_read_file_cache(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import read_file

    r1 = read_file.invoke({"path": "README.md"})
    r2 = read_file.invoke({"path": "README.md"})
    assert "[cached]" not in r1
    assert "[cached]" in r2


def test_read_file_cache_invalidated_on_write(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import read_file, write_file

    write_file.invoke({"path": "tmp.txt", "content": "v1"})
    read_file.invoke({"path": "tmp.txt"})
    write_file.invoke({"path": "tmp.txt", "content": "v2"})
    r = read_file.invoke({"path": "tmp.txt"})
    assert "v2" in r
    assert "[cached]" not in r


def test_read_file_rejects_traversal(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import read_file

    result = read_file.invoke({"path": "../../etc/passwd"})
    assert "ERROR" in result


def test_glob_empty_result(tmp_path):
    _build_workspace(tmp_path)
    from tools.file_ops import glob_files

    result = glob_files.invoke({"pattern": "**/*.xyz"})
    assert "未找到" in result
