"""Agent 配置。

配置分层（从高到低）：
1. 项目级 <project>/.coding-agent/config.yaml  — provider/model/temperature 等
2. 全局   ~/.coding-agent/config.yaml            — 全局默认（可选）
3. API Key ~/.coding-agent/credentials.yaml     — 各 provider 的 key
4. 环境变量 AGENT_* / DASHSCOPE_API_KEY 等
5. .env                                         — 兼容旧配置
6. 硬编码默认值

temperature 可为 None —— 表示不发送该参数（兼容 kimi-k3、o1 等不支持
temperature 的模型）。

base_url 从 providers 表查，不硬编码；这样切换 Provider 时不会打到
错误的端点（如 qwen 打到 OpenAI 官方会被 403 拒绝）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_AGENT_HOME = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """加载 Agent 自身目录的 .env（作为兜底，不覆盖已有环境变量）。"""
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
    """解析用户项目路径。

    优先级：显式参数 > AGENT_PROJECT 环境变量 > 当前工作目录。
    拒绝解析到 Agent 自身目录。
    """
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
    """按优先级加载 API Key。

    1. 全局凭据文件里该 provider 的 key
    2. 该 provider 对应的环境变量
    3. AGENT_API_KEY 显式指定
    4. 常见环境变量（兜底）
    """
    # 1. 全局凭据
    if provider_id:
        try:
            from agent.credentials import get_api_key
            key = get_api_key(provider_id)
            if key:
                return key
        except Exception:
            pass

    # 2. provider 特定环境变量
    if env_key:
        key = os.getenv(env_key, "")
        if key:
            return key

    # 3. AGENT_API_KEY 显式指定
    explicit = os.getenv("AGENT_API_KEY", "")
    if explicit:
        return explicit

    # 4. 常见环境变量兜底
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
    """解析 temperature。

    None / 空字符串 / "none" / "default" → None（不发送该参数）
    有效数字 → float
    无效值 → None（降级为不发送）
    """
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
    """解析布尔配置。

    支持 True / False / "true" / "false" / "1" / "0" / "yes" / "no" /
    "on" / "off"。
    """
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

    # 路径
    project_path: Path
    agent_home: Path

    # 模型
    model: str
    model_provider: str          # openai / anthropic
    provider_id: str             # qwen / openai / deepseek / ...
    base_url: str
    api_key: str
    model_window: int
    # None = 不发送 temperature 参数（兼容部分模型）
    temperature: float | None
    timeout: int

    # 运行限制
    max_iterations: int = 25
    verbose: bool = True
    strict_lint: bool = False
    enable_mcp: bool = False

    # ---------- 缓存字段（不参与序列化） ----------
    _meta_dir_cache: Path | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _index_dir_cache: Path | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _trajectory_dir_cache: Path | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _memory_dir_cache: Path | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _session_dir_cache: Path | None = field(
        default=None, init=False, repr=False, compare=False
    )

    # ========================================================
    # 加载器
    # ========================================================

    @classmethod
    def load(
        cls,
        project_path: str | Path | None = None,
        **overrides,
    ) -> "AgentConfig":
        """从多级配置加载 AgentConfig。

        优先级：
        1. overrides（显式传入）
        2. 项目级配置
        3. 全局配置
        4. 环境变量
        5. 硬编码默认值
        """
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

        # 从 providers 表查默认 langchain_provider
        from agent.providers import get_provider
        provider_info = get_provider(provider_id)

        model_provider = (
            get("langchain_provider")
            or (provider_info.langchain_provider if provider_info else "openai")
        )

        env_key = provider_info.env_key if provider_info else ""
        api_key = get("api_key", "") or _load_api_key(provider_id, env_key)

        base_url = get("base_url", "")
        if not base_url and provider_info:
            base_url = provider_info.base_url

        default_model = provider_info.default_model if provider_info else "qwen-max"

        # temperature 解析：None 表示不发送
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
    ) -> "AgentConfig":
        """测试专用构造器：模拟老接口 AgentConfig(workspace=..., model=...)。

        Args:
            workspace: 项目路径。
            model: 形如 "qwen:qwen-max" 或 "openai:gpt-4o" 的字符串。

        关键：
            - base_url 从 providers 表查（不再硬编码 ""）
            - api_key 从对应环境变量读（DASHSCOPE_API_KEY / OPENAI_API_KEY 等）
            - model_provider 从 providers 表查（qwen → openai 兼容，anthropic → anthropic）
        """
        import os as _os

        provider_id = "openai"
        model_name = model
        if ":" in model:
            provider_id, model_name = model.split(":", 1)

        # ★ 从 providers 表查 base_url / env_key / langchain_provider
        from agent.providers import get_provider
        info = get_provider(provider_id)

        base_url = info.base_url if info else ""
        env_key = info.env_key if info else ""

        # API Key 优先级：
        # 1. provider 对应的环境变量（如 DASHSCOPE_API_KEY）
        # 2. 通用的 OPENAI_API_KEY
        # 3. dummy（部分本地端点如 Ollama 不需要 key）
        api_key = (
            _os.getenv(env_key, "")
            or _os.getenv("OPENAI_API_KEY", "")
            or "dummy"
        )

        return cls(
            project_path=Path(workspace).resolve(),
            agent_home=_AGENT_HOME,
            model=model_name,
            model_provider=(
                info.langchain_provider if info else "openai"
            ),
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
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
        """Agent 元数据目录。缓存 mkdir 结果，避免每次访问都做系统调用。"""
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
            raise ValueError(
                "API Key 未设置。\n"
                "请重新运行 `coding-agent` 触发配置向导。"
            )
        if self.temperature is not None:
            if self.temperature < 0 or self.temperature > 2:
                raise ValueError(
                    f"temperature 必须在 [0, 2]: {self.temperature}"
                )
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
            "temperature": (
                self.temperature if self.temperature is not None else "(不发送)"
            ),
            "timeout": self.timeout,
            "max_iterations": self.max_iterations,
            "enable_mcp": self.enable_mcp,
        }

    def ensure_gitignore(self) -> None:
        """确保 .coding-agent/ 被忽略。

        优化：先读一次，命中就返回，避免每次都写文件。
        """
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
            # gitignore 写入失败不应阻塞 Agent 启动
            pass
