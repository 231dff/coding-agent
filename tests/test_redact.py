"""日志脱敏测试。"""

from __future__ import annotations


def test_redact_api_key():
    from observability.redact import redact_dict

    result = redact_dict(
        {
            "api_key": "sk-abc123",
            "model": "qwen-max",
        }
    )
    assert result["api_key"] == "***"
    assert result["model"] == "qwen-max"


def test_redact_token_variants():
    from observability.redact import redact_dict

    result = redact_dict(
        {
            "access_token": "abc",
            "auth_token": "def",
            "refresh_token": "ghi",
            "password": "x",
            "secret": "y",
            "credential": "z",
            "private_key": "k",
        }
    )
    for v in result.values():
        assert v == "***"


def test_redact_dsn_password():
    from observability.redact import redact_dict

    result = redact_dict(
        {
            "dsn": "postgresql://user:password123@host:5432/db",
        }
    )
    assert "password123" not in result["dsn"]
    assert "user:***@host" in result["dsn"]


def test_redact_deep_nested():
    from observability.redact import redact_deep

    result = redact_deep(
        {
            "config": {
                "openai": {
                    "api_key": "sk-xxx",
                    "base_url": "https://api.com",
                },
            },
        }
    )
    assert result["config"]["openai"]["api_key"] == "***"
    assert result["config"]["openai"]["base_url"] == "https://api.com"


def test_redact_non_dict():
    from observability.redact import redact_dict

    assert redact_dict("string") == "string"
    assert redact_dict(None) is None
