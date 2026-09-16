"""Day 2-3: 文件工具单元测试。"""

import pytest

from tools.file_ops import (
    edit_file,
    glob_files,
    grep_search,
    ls_dir,
    read_file,
    set_workspace,
    write_file,
)


@pytest.fixture(autouse=True)
def workspace(tmp_path):
    set_workspace(tmp_path)
    (tmp_path / "hello.py").write_text("def greet(name):\n    return f'Hello, {name}'\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "data.txt").write_text("line one\nline two\nline three\n")
    return tmp_path


def test_read_file_full(workspace):
    result = read_file.invoke({"path": "hello.py"})
    assert "def greet" in result


def test_read_file_range(workspace):
    result = read_file.invoke({"path": "hello.py", "start_line": 0, "end_line": 1})
    assert "def greet" in result
    assert "return" not in result


def test_write_file_creates_backup(workspace):
    write_file.invoke({"path": "hello.py", "content": "new content"})
    assert (workspace / "hello.py.bak").exists()
    assert (workspace / "hello.py").read_text() == "new content"


def test_edit_file_unique(workspace):
    result = edit_file.invoke(
        {
            "path": "hello.py",
            "old_string": "def greet",
            "new_string": "def say_hello",
        }
    )
    assert "OK" in result
    assert "say_hello" in (workspace / "hello.py").read_text()


def test_edit_file_not_unique(workspace):
    result = edit_file.invoke(
        {
            "path": "hello.py",
            "old_string": "e",
            "new_string": "X",
        }
    )
    assert "不唯一" in result or "ERROR" in result


def test_edit_file_not_found(workspace):
    result = edit_file.invoke(
        {
            "path": "hello.py",
            "old_string": "nonexistent_xyz",
            "new_string": "X",
        }
    )
    assert "ERROR" in result


def test_glob_files(workspace):
    result = glob_files.invoke({"pattern": "**/*.py"})
    assert "hello.py" in result


def test_grep_search(workspace):
    result = grep_search.invoke({"pattern": "line two", "path": "."})
    assert "line two" in result


def test_ls_dir(workspace):
    result = ls_dir.invoke({"path": "."})
    assert "hello.py" in result
    assert "sub/" in result
