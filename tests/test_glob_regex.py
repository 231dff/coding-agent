"""_glob_to_regex 正则翻译测试。

测试目标：
- `*.py` 只匹配根目录
- `**/*.py` 匹配任意深度
- `src/**/*.ts` 前缀限定
- `?` 单字符通配
- 特殊字符正确转义
"""

from __future__ import annotations

import pytest

from tools.file_ops import _glob_to_regex


@pytest.mark.parametrize(
    "pattern,should_match,should_not_match",
    [
        # 单层
        ("*.py", ["main.py", "a.py"], ["src/main.py", "main.js"]),
        # 任意深度
        ("**/*.py", ["main.py", "src/main.py", "a/b/c/d.py"], ["main.js", "src/main.ts"]),
        # 前缀限定
        ("src/**/*.ts", ["src/a.ts", "src/b/c.ts"], ["a.ts", "test/src/a.ts", "src/a.js"]),
        # src 下一层
        ("src/*.py", ["src/main.py"], ["main.py", "src/sub/main.py"]),
        # 单字符
        ("test_?.py", ["test_a.py", "test_1.py"], ["test_ab.py", "test_.py"]),
        # 混合
        ("**/test_*.py", ["test_a.py", "src/test_b.py", "a/b/test_c.py"], ["main.py", "test.py"]),
    ],
)
def test_glob_patterns(pattern, should_match, should_not_match):
    regex = _glob_to_regex(pattern)

    for s in should_match:
        assert regex.match(s), f"{pattern!r} 应匹配 {s!r}"
    for s in should_not_match:
        assert not regex.match(s), f"{pattern!r} 不应匹配 {s!r}"


def test_regex_special_chars_escaped():
    """`(`、`)`、`.` 等应被转义，不当作 regex 语法。"""
    regex = _glob_to_regex("a(b).py")
    assert regex.match("a(b).py")
    assert not regex.match("aXb.py")


def test_leading_dot_slash_ignored():
    """开头的 ./ 会被剥掉。"""
    r1 = _glob_to_regex("*.py")
    r2 = _glob_to_regex("./*.py")
    assert r1.match("main.py")
    assert r2.match("main.py")
