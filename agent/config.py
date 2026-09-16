"""Agent 配置。

配置分层（从高到低）：
1. 项目级 <project>/.coding-agent/config.yaml
2. 全局   ~/.coding-agent/config.yaml
3. API Key ~/.coding-agent/credentials.yaml
4. 环境变量 AGENT_* / DASHSCOPE_API_KEY 等
5. .env
6. 硬编码默认值

temperature 可为 None —— 表示不发送该参数。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_AGENT_HOME = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    agent_env = _AGENT_HOME / ".env"
    if agent_env.exists():
        load_dotenv(dotenv_path=agent_env, override=False)
    else:
        load_dotenv(override=False)


_load_env()


# ============================================================
# 配置文件路径
# ============================================================


def global_config_file() -> Path:
    return Path.home() / ".coding-agent" / "config.yaml"


def project_config_file(project_path: Path) -> Path:
    return project_path / ".coding-agent" / "config.yaml"


def load_yaml_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_yaml_config(path: Path, data: dict) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# ============================================================
# 项目路径解析
# ============================================================


def resolve_project_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        candidate = Path(explicit).resolve()
    elif os.getenv("AGENT_PROJECT"):
        candidate = Path(os.getenv("AGENT_PROJECT")).resolve()
    else:
        candidate = Path.cwd().resolve()

    if not candidate.exists():
        raise ValueError(f"项目路径不存在: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"不是目录: {candidate}")

    if candidate == _AGENT_HOME or _AGENT_HOME in candidate.parents:
        raise ValueError(
            f"❌ 目标项目不能是 Agent 自身的目录！\n"
            f"   Agent 自身: {_AGENT_HOME}\n"
            f"   你指定的:  {candidate}\n"
            f"   正确用法: cd 到你要操作的项目目录，或用 --project 指定"
        )
    if candidate in _AGENT_HOME.parents:
        raise ValueError("❌ 用户项目不能包含 Agent 自身目录！")

    return candidate


# ============================================================
# API Key 加载
# ============================================================


def _load_api_key(provider_id: str = "", env_key: str = "") -> str:
    if provider_id:
        try:
            from agent.credentials import get_api_key

            key = get_api_key(provider_id)
            if key:
                return key
        except Exception:
            pass

    if env_key:
        key = os.getenv(env_key, "")
        if key:
            return key

    explicit = os.getenv("AGENT_API_KEY", "")
    if explicit:
        return explicit

    for name in (
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "ZHIPU_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        key = os.getenv(name, "")
        if key:
            return key

    return ""


# ============================================================
# 解析辅助
# ============================================================


def _parse_temperature(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("", "none", "default", "null", "skip"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _parse_bool(raw, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off", ""):
        return False
    return default


# ============================================================
# AgentConfig
# ============================================================


@dataclass
class AgentConfig:
    """Agent 运行时配置。"""

    project_path: Path
    agent_home: Path

    model: str
    model_provider: str
    provider_id: str
    base_url: str
    api_key: str
    model_window: int
    temperature: float | None
    timeout: int

    max_iterations: int = 25
    verbose: bool = True
    strict_lint: bool = False
    enable_mcp: bool = False

    _meta_dir_cache: Path | None = field(default=None, init=False, repr=False, compare=False)
    _index_dir_cache: Path | None = field(default=None, init=False, repr=False, compare=False)
    _trajectory_dir_cache: Path | None = field(default=None, init=False, repr=False, compare=False)
    _memory_dir_cache: Path | None = field(default=None, init=False, repr=False, compare=False)
    _session_dir_cache: Path | None = field(default=None, init=False, repr=False, compare=False)

    # ========================================================
    # 加载器
    # ========================================================

    @classmethod
    def load(
        cls,
        project_path: str | Path | None = None,
        **overrides,
    ) -> AgentConfig:
        pp = resolve_project_path(project_path)

        proj_cfg = load_yaml_config(project_config_file(pp))
        glob_cfg = load_yaml_config(global_config_file())

        def get(key: str, default=None):
            if key in overrides:
                return overrides[key]
            if key in proj_cfg:
                return proj_cfg[key]
            if key in glob_cfg:
                return glob_cfg[key]
            env_val = os.getenv(f"AGENT_{key.upper()}")
            if env_val is not None:
                return env_val
            return default

        provider_id = get("provider", "qwen")

        from agent.providers import get_provider

        provider_info = get_provider(provider_id)

        model_provider = get("langchain_provider") or (
            provider_info.langchain_provider if provider_info else "openai"
        )

        env_key = provider_info.env_key if provider_info else ""
        api_key = get("api_key", "") or _load_api_key(provider_id, env_key)

        base_url = get("base_url", "")
        if not base_url and provider_info:
            base_url = provider_info.base_url

        default_model = provider_info.default_model if provider_info else "qwen-max"

        temperature = _parse_temperature(get("temperature", None))

        return cls(
            project_path=pp,
            agent_home=_AGENT_HOME,
            model=get("model", default_model),
            model_provider=model_provider,
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
            model_window=int(get("model_window", 200000)),
            temperature=temperature,
            timeout=int(get("timeout", 120)),
            max_iterations=int(get("max_iterations", 25)),
            verbose=_parse_bool(get("verbose", "true"), default=True),
            strict_lint=_parse_bool(get("strict_lint", "false"), default=False),
            enable_mcp=_parse_bool(get("enable_mcp", "false"), default=False),
        )

    @classmethod
    def for_test(
        cls,
        workspace: str | Path,
        model: str = "openai:gpt-4o",
    ) -> AgentConfig:
        """测试专用构造器：模拟老接口 AgentConfig(workspace=..., model=...)。

        Args:
            workspace: 项目路径。
            model: 形如 "openai:gpt-5.5" 的字符串。
        """
        provider_id = "openai"
        model_name = model
        if ":" in model:
            provider_id, model_name = model.split(":", 1)

        return cls(
            project_path=Path(workspace).resolve(),
            agent_home=_AGENT_HOME,
            model=model_name,
            model_provider="openai",
            provider_id=provider_id,
            base_url="",
            api_key="dummy",
            model_window=200000,
            temperature=None,
            timeout=120,
        )

    # ========================================================
    # 派生路径（带缓存）
    # ========================================================

    @property
    def workspace(self) -> str:
        return str(self.project_path)

    @property
    def meta_dir(self) -> Path:
        if self._meta_dir_cache is None:
            d = self.project_path / ".coding-agent"
            d.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "_meta_dir_cache", d)
        return self._meta_dir_cache

    @property
    def index_dir(self) -> Path:
        if self._index_dir_cache is None:
            d = self.meta_dir / "index"
            d.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "_index_dir_cache", d)
        return self._index_dir_cache

    @property
    def trajectory_dir(self) -> Path:
        if self._trajectory_dir_cache is None:
            d = self.meta_dir / "trajectories"
            d.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "_trajectory_dir_cache", d)
        return self._trajectory_dir_cache

    @property
    def memory_dir(self) -> Path:
        if self._memory_dir_cache is None:
            d = self.meta_dir / "memory"
            d.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "_memory_dir_cache", d)
        return self._memory_dir_cache

    @property
    def session_dir(self) -> Path:
        if self._session_dir_cache is None:
            d = self.meta_dir / "sessions"
            d.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "_session_dir_cache", d)
        return self._session_dir_cache

    # ========================================================
    # 校验
    # ========================================================

    def validate(self) -> None:
        if not self.model:
            raise ValueError("model 不能为空")
        if ":" in self.model and self.model_provider == "openai":
            raise ValueError(f"model 不应带 provider 前缀: {self.model!r}")
        if not self.project_path.is_dir():
            raise ValueError(f"项目路径不存在: {self.project_path}")
        if not self.api_key and self.provider_id != "ollama":
            raise ValueError("API Key 未设置。\n请重新运行 `coding-agent` 触发配置向导。")
        if self.temperature is not None:
            if self.temperature < 0 or self.temperature > 2:
                raise ValueError(f"temperature 必须在 [0, 2]: {self.temperature}")
        if self.timeout < 10:
            raise ValueError(f"timeout 至少 10 秒: {self.timeout}")
        if self.model_window < 1000:
            raise ValueError(f"model_window 至少 1000: {self.model_window}")
        if self.max_iterations < 1:
            raise ValueError(f"max_iterations 至少 1: {self.max_iterations}")

    def to_dict(self) -> dict:
        return {
            "project_path": str(self.project_path),
            "agent_home": str(self.agent_home),
            "provider": self.provider_id,
            "model": self.model,
            "model_provider": self.model_provider,
            "base_url": self.base_url,
            "api_key": "***" if self.api_key else "(empty)",
            "model_window": self.model_window,
            "temperature": (self.temperature if self.temperature is not None else "(不发送)"),
            "timeout": self.timeout,
            "max_iterations": self.max_iterations,
            "enable_mcp": self.enable_mcp,
        }

    def ensure_gitignore(self) -> None:
        gitignore = self.project_path / ".gitignore"
        entry = ".coding-agent/"

        try:
            if gitignore.exists():
                content = gitignore.read_text(encoding="utf-8")
                if entry in content:
                    return
                if not content.endswith("\n"):
                    content += "\n"
                content += f"\n# Agent metadata\n{entry}\n"
                gitignore.write_text(content, encoding="utf-8")
            else:
                gitignore.write_text(
                    f"# Agent metadata\n{entry}\n",
                    encoding="utf-8",
                )
        except Exception:
            pass
