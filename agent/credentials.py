"""全局 API Key 管理。

存储：~/.coding-agent/credentials.yaml
结构：
    qwen:
      api_key: sk-...
    openai:
      api_key: sk-...
    deepseek:
      api_key: sk-...

API Key 跨项目共享，避免每次进新项目都输 key。
"""

from __future__ import annotations

from pathlib import Path

import yaml


def credentials_file() -> Path:
    """返回全局凭据文件路径。"""
    return Path.home() / ".coding-agent" / "credentials.yaml"


def load_credentials() -> dict:
    """加载所有凭据。

    Returns:
        {provider_id: {"api_key": "sk-..."}, ...}
    """
    path = credentials_file()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_api_key(provider_id: str) -> str:
    """获取指定 provider 的 API Key。

    Args:
        provider_id: provider 标识（如 "qwen"、"openai"）。

    Returns:
        API Key 字符串，不存在时返回空字符串。
    """
    return load_credentials().get(provider_id, {}).get("api_key", "")


def set_api_key(provider_id: str, api_key: str) -> None:
    """保存 API Key 到全局凭据文件。

    Args:
        provider_id: provider 标识。
        api_key: API Key。
    """
    data = load_credentials()
    data.setdefault(provider_id, {})["api_key"] = api_key

    path = credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def remove_api_key(provider_id: str) -> None:
    """删除指定 provider 的 API Key。"""
    data = load_credentials()
    if provider_id in data:
        del data[provider_id]
        path = credentials_file()
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def list_providers_with_keys() -> list[str]:
    """列出已保存 key 的 provider。

    Returns:
        已保存 key 的 provider_id 列表。
    """
    return list(load_credentials().keys())
