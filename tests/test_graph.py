"""Day 23-24: 图测试。"""

from agent.test_loop import parse_test_output


def test_parse_passed():
    output = "5 passed in 0.12s"
    result = parse_test_output(output)
    assert result.passed
    assert result.total == 5
    assert result.failed == 0


def test_parse_failed():
    output = "2 passed, 1 failed in 0.5s\nFAILED tests/test_x.py::test_y"
    result = parse_test_output(output)
    assert not result.passed
    assert result.failed == 1
    assert len(result.errors) > 0


def test_parse_errors():
    output = "3 passed, 1 error in 0.3s\nERROR tests/test_a.py::test_b"
    result = parse_test_output(output)
    assert not result.passed
    assert result.failed == 1
