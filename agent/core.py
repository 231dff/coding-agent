"""agent/core.py — Coding Agent 装配入口。

集成：
- 多 Provider 模型支持
- 沙箱工厂（SandboxPool，不池化）
- 条件化思考（ThinkingRouter）
- Content 剥离（ContentStripper）
- 会话持久化（SQLite checkpointer）
- 双层记忆（Cards + Retrieval）
- LangGraph Store 后端
- 幂等性保护（IdempotencyMiddleware）
- MCP 渐进式披露（mcp_list_servers / mcp_use_server 元工具）
- P1-1: 写操作后自动跑测试（AutoTestMiddleware）
- P1-2: 独立 Reviewer 子 Agent（review_changes 工具）
- P1-3: 结构化交付报告（generate_summary_report 工具）
- P2: 持续进化闭环（经验归档 + /evolve 提案生成）
- P3: 多 Agent 并行协作（管理者模式 + 级联终止）

性能优化：
- 沙箱启动与代码库分析并行执行
- 检索器延迟初始化（不阻塞启动）

安全：
- 幂等性中间件防止重复写操作
- 日志脱敏（见 observability/redact.py）
- 沙箱 release 不做任何删除（见 sandbox/pool.py）
"""

from __future__ import annotations

import concurrent.futures
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents import create_agent

from agent.checkpointer import build_checkpointer
from agent.config import AgentConfig

# P2: 经验归档
from agent.evolution.store import EvolutionStore, set_store

# ★ P3: 并行执行器
from agent.parallel import ParallelExecutor, set_executor

# P1-2: Reviewer 子 Agent
from agent.reviewer import Reviewer
from codebase.background_indexer import BackgroundIndexer
from codebase.call_graph import CallGraph, create_call_tools
from codebase.dep_graph import DependencyGraph, create_dep_tools
from codebase.impact import ImpactAnalyzer, create_impact_tool
from codebase.indexer import (
    CodeIndexer,
    create_index_status_tool,
    create_search_tool,
)
from codebase.parser import CodeParser
from codebase.repo_map import RepoMapBuilder, create_repo_map_tool
from context.assembly import ContextAssembler
from context.status_bar import AgentStatusBar
from memory.cards import user_card_repo
from memory.store import (
    get_store as get_memory_store,
)
from memory.store import (
    store_backend_info,
)

# P1-1: 自动测试中间件
from middleware.auto_test import AutoTestMiddleware
from middleware.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerMiddleware,
)
from middleware.content_stripper import create_content_stripper_middleware
from middleware.context_compaction import (
    CompactionPipelineConfig,
    ContextCompactionMiddleware,
)
from middleware.dependency_check import create_dependency_check_middleware
from middleware.idempotency import create_idempotency_middleware
from middleware.metrics import MetricsMiddleware
from middleware.prompt_cache import create_prompt_cache_middleware
from middleware.retrieval_inject import create_retrieval_inject_middleware
from middleware.status_bar import StatusBarMiddleware
from middleware.thinking_router import create_thinking_router_middleware
from middleware.tool_filter import create_tool_filter_middleware
from middleware.tool_search import create_tool_search_tool
from middleware.trajectory import TrajectoryMiddleware
from observability.logger import get_logger
from observability.trajectory_writer import TrajectoryWriter
from sandbox.docker_backend import DockerSandbox
from sandbox.patch import create_apply_patch_tool
from sandbox.pool import SandboxPool
from skills.loader import create_load_skill_tool
from skills.registry import SkillRegistry
from tools.context_ops import CONTEXT_TOOLS
from tools.context_ops import bind as bind_context
from tools.lint import validate_tools
from tools.parallel_ops import PARALLEL_TOOLS
from tools.registry import build_default_tools

# P1-3: 结构化交付报告
from tools.report_ops import REPORT_TOOLS
from tools.report_ops import bind as bind_report
from tools.review_ops import REVIEW_TOOLS
from tools.review_ops import bind as bind_review
from tools.sandbox_ops import SANDBOX_TOOLS
from tools.sandbox_ops import bind as bind_sandbox
from tools.status_ops import STATUS_TOOLS
from tools.status_ops import bind as bind_status
from tools.subagent_ops import (
    SUBAGENT_TOOLS,
    bind_graphs,
)
from tools.subagent_ops import (
    bind as bind_subagent,
)
from tools.test_ops import TEST_TOOLS
from tools.test_ops import bind as bind_test
from tools.transaction_ops import TRANSACTION_TOOLS
from tools.transaction_ops import bind as bind_tx

log = get_logger("core")

try:
    from mcp_client.client import MCPConfig, load_mcp_tools_sync

    _MCP_AVAILABLE = True
except ImportError as _e:
    log.warning("mcp_import_failed", error=str(_e))
    MCPConfig = None  # type: ignore
    load_mcp_tools_sync = None  # type: ignore
    _MCP_AVAILABLE = False


# ============================================================
# 环境变量开关
# ============================================================


def _env_bool(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).lower() == "true"


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _is_eval_mode() -> bool:
    return _env_bool("AGENT_EVAL_MODE", "false")


# ============================================================
# 沙箱配置
# ============================================================


@dataclass
class SandboxSettings:
    """沙箱运行时配置。"""

    network: bool = False
    memory_limit: str = "2g"
    cpu_limit: float = 2.0
    image: str | None = None

    @classmethod
    def from_env(cls) -> "SandboxSettings":
        return cls(
            network=_env_bool("AGENT_SANDBOX_NETWORK", "false"),
            memory_limit=os.getenv("AGENT_SANDBOX_MEMORY", "2g"),
            cpu_limit=_env_float("AGENT_SANDBOX_CPU", 2.0),
            image=os.getenv("AGENT_SANDBOX_IMAGE") or None,
        )


# ============================================================
# 全局沙箱工厂
# ============================================================

_SANDBOX_POOL: SandboxPool | None = None
_SANDBOX_POOL_LOCK = threading.Lock()


def _get_sandbox_pool() -> SandboxPool:
    global _SANDBOX_POOL
    with _SANDBOX_POOL_LOCK:
        if _SANDBOX_POOL is None:
            _SANDBOX_POOL = SandboxPool(size=1)
            _SANDBOX_POOL.start()
        return _SANDBOX_POOL


# ============================================================
# 资源加载
# ============================================================


def load_system_prompt(agent_home: Path) -> str:
    if _is_eval_mode():
        minimal = agent_home / "prompts" / "system_minimal.md"
        if minimal.exists():
            return minimal.read_text(encoding="utf-8")

    path = agent_home / "prompts" / "system_v1.md"
    if not path.exists():
        raise FileNotFoundError(f"系统提示词文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def load_project_memory(project_path: Path) -> str:
    if _is_eval_mode():
        return ""
    for name in ("AGENTS.md", "CLAUDE.md", "CODING_AGENT.md"):
        p = project_path / name
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def render_tool_definitions(tools: list[Any]) -> str:
    lines = []
    for t in sorted(tools, key=lambda x: x.name):
        desc = (t.description or "").split("\n", 1)[0].strip()
        lines.append(f"- {t.name}: {desc}")
    return "\n".join(lines)


# ============================================================
# MCP 加载
# ============================================================


def build_mcp_config(agent_home: Path, project_path: Path | None = None):
    if not _MCP_AVAILABLE:
        raise RuntimeError("MCP 不可用（mcp_client.client 导入失败）")

    from mcp_client.client import load_mcp_servers

    include_builtin = _env_bool("AGENT_MCP_INCLUDE_BUILTIN", "false")
    return load_mcp_servers(
        project_path=project_path,
        agent_home=agent_home,
        include_builtin=include_builtin,
        verbose=True,
    )


def _load_mcp_in_thread_with_mapping(
    config, timeout: float = 60.0
) -> tuple[list[Any], dict[str, str]]:
    if load_mcp_tools_sync is None:
        return [], {}

    def _run():
        return load_mcp_tools_sync(config)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_run)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.warning("mcp_load_timeout", timeout_s=timeout)
            return [], {}
        except Exception as e:
            log.warning("mcp_load_failed", error=str(e))
            return [], {}


def _aggregate_server_to_tools(
    mcp_tools: list[Any],
    tool_to_server: dict[str, str],
    configured_servers: list[str],
) -> dict[str, list[str]]:
    server_to_tools: dict[str, list[str]] = {}

    for tool_name, server in tool_to_server.items():
        server_to_tools.setdefault(server, []).append(tool_name)

    for t in mcp_tools:
        if t.name in tool_to_server:
            continue
        for s in configured_servers:
            if t.name.startswith(f"{s}_") or t.name.startswith(f"mcp_{s}_"):
                server_to_tools.setdefault(s, []).append(t.name)
                break

    return server_to_tools


# ============================================================
# LLM 初始化
# ============================================================


def build_llm(cfg: AgentConfig):
    if cfg.model_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        log.info(
            "llm_build",
            backend="anthropic",
            provider=cfg.provider_id,
            model=cfg.model,
        )
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "api_key": cfg.api_key,
            "timeout": cfg.timeout,
            "max_retries": 2,
        }
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature

        return ChatAnthropic(**kwargs)

    from langchain_openai import ChatOpenAI

    log.info(
        "llm_build",
        backend="openai-compatible",
        provider=cfg.provider_id,
        model=cfg.model,
        base_url=cfg.base_url or "(default)",
    )

    kwargs: dict[str, Any] = {
        "model": cfg.model,
        "api_key": cfg.api_key or "dummy",
        "max_retries": 2,
        "timeout": cfg.timeout,
        "stream_usage": True,
        "model_kwargs": {
            "prompt_cache_key": "coding-agent-v1",
        },
    }
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url

    return ChatOpenAI(**kwargs)


def _build_compaction_llm(cfg: AgentConfig):
    cheap_model = os.getenv("AGENT_COMPACTION_MODEL", "")
    if not cheap_model:
        return build_llm(cfg)

    # 浅拷贝 + 覆盖 model（不依赖 dataclasses，兼容 pydantic / 自定义类）
    import copy as _copy

    try:
        cheap_cfg = _copy.copy(cfg)
        cheap_cfg.model = cheap_model
    except Exception:
        return build_llm(cfg)

    return build_llm(cheap_cfg)


# P1-2: Reviewer 用 LLM
def _build_reviewer_llm(cfg: AgentConfig):
    """Reviewer 用 LLM。优先 AGENT_REVIEWER_MODEL，否则复用主模型。"""
    reviewer_model = os.getenv("AGENT_REVIEWER_MODEL", "")
    if not reviewer_model:
        return build_llm(cfg)

    import copy as _copy

    try:
        reviewer_cfg = _copy.copy(cfg)
        reviewer_cfg.model = reviewer_model
        reviewer_cfg.timeout = int(os.getenv("AGENT_REVIEWER_TIMEOUT", "45"))
    except Exception:
        return build_llm(cfg)

    return build_llm(reviewer_cfg)


# ============================================================
# 运行时句柄
# ============================================================


@dataclass
class AgentRuntime:
    """Agent 运行时句柄。"""

    agent: Any
    sandbox: DockerSandbox
    assembler: ContextAssembler
    tools: list[Any]
    bg_indexer: BackgroundIndexer
    config: AgentConfig
    skill_registry: SkillRegistry | None = None
    status_bar: AgentStatusBar | None = None
    circuit_breaker: CircuitBreakerMiddleware | None = None
    trajectory_writer: TrajectoryWriter | None = None
    metrics_queue: Any = None
    checkpointer: Any = None
    sandbox_from_pool: bool = False
    # P2: 经验归档存储
    evolution_store: Any = None
    # ★ P3: 并行执行器
    parallel_executor: Any = None

    _planning_graph: Any = field(default=None, init=False, repr=False)
    _repair_graph: Any = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def invoke(self, *args, **kwargs):
        return self.agent.invoke(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        return await self.agent.ainvoke(*args, **kwargs)

    def stream(self, *args, **kwargs):
        return self.agent.stream(*args, **kwargs)

    async def astream(self, *args, **kwargs):
        return await self.agent.astream(*args, **kwargs)

    def stream_events(self, *args, **kwargs):
        return self.agent.stream_events(*args, **kwargs)

    async def astream_events(self, *args, **kwargs):
        return await self.agent.astream_events(*args, **kwargs)

    def get_state(self, *args, **kwargs):
        return self.agent.get_state(*args, **kwargs)

    @property
    def planning_graph(self):
        if self._planning_graph is None:
            from agent.graph import build_planning_graph

            self._planning_graph = build_planning_graph(self.agent, self.checkpointer)
        return self._planning_graph

    @property
    def repair_graph(self):
        if self._repair_graph is None:
            from agent.test_loop import build_repair_graph

            def _exec(cmd: str):
                return self.sandbox.exec(cmd)

            self._repair_graph = build_repair_graph(self.agent, _exec, self.checkpointer)
        return self._repair_graph

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        try:
            self.bg_indexer.stop(timeout=3.0)
        except Exception:
            pass

        try:
            if self.sandbox_from_pool:
                _get_sandbox_pool().release(self.sandbox)
            else:
                self.sandbox.stop()
        except Exception:
            pass

        try:
            if self.trajectory_writer:
                self.trajectory_writer.close()
        except Exception:
            pass

    def __enter__(self) -> "AgentRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def check_prefix_stability(self) -> bool:
        return self.assembler.check_prefix_stability()

    def index_ready(self) -> bool:
        return self.bg_indexer.is_ready()


# ============================================================
# 沙箱 / 代码库
# ============================================================


def _build_sandbox_kwargs(settings: SandboxSettings) -> dict:
    kwargs: dict[str, Any] = {
        "memory_limit": settings.memory_limit,
        "cpu_limit": settings.cpu_limit,
        "network": settings.network,
    }
    if settings.image:
        kwargs["image"] = settings.image
    return kwargs


def _start_sandbox(cfg: AgentConfig, log) -> tuple[DockerSandbox, bool]:
    settings = SandboxSettings.from_env()
    from_pool = False

    log.info(
        "sandbox_start",
        network=settings.network,
        memory=settings.memory_limit,
        cpu=settings.cpu_limit,
        image=settings.image or "(default)",
    )

    if settings.network:
        log.warning(
            "sandbox_network_enabled",
            hint="Agent 可以访问外网，仅在信任的场景使用",
        )

    try:
        sb = _get_sandbox_pool().acquire(str(cfg.project_path))
        from_pool = True
        return sb, from_pool
    except Exception as e:
        log.warning("sandbox_factory_acquire_failed", error=str(e))
        sb = DockerSandbox(
            str(cfg.project_path),
            **_build_sandbox_kwargs(settings),
        )
        sb.start()
        return sb, from_pool


def _build_codebase(cfg: AgentConfig, log) -> tuple[Any, Any, Any, Any]:
    parser = CodeParser(str(cfg.project_path))
    dep_graph = DependencyGraph(parser)
    call_graph = CallGraph(parser)

    try:
        dep_graph.build()
        call_graph.build()
    except Exception as e:
        log.warning("codebase_build_failed", error=str(e))

    analyzer = ImpactAnalyzer(call_graph, dep_graph)
    return parser, dep_graph, call_graph, analyzer


# ============================================================
# 主装配函数
# ============================================================


def build_agent(cfg: AgentConfig) -> AgentRuntime:
    """组装完整的 Coding Agent。"""
    from observability.logger import get_logger

    log = get_logger("core")

    eval_mode = _is_eval_mode()

    t0 = time.time()
    cfg.validate()

    log.info(
        "agent_build_start",
        provider=cfg.provider_id,
        model=cfg.model,
        project=str(cfg.project_path),
        eval_mode=eval_mode,
    )

    # ---------- 0. LLM + checkpointer ----------
    llm = build_llm(cfg)
    compaction_llm = _build_compaction_llm(cfg)
    checkpointer = build_checkpointer(cfg.meta_dir)

    if not eval_mode:
        try:
            _ = get_memory_store()
        except Exception as e:
            log.warning("memory_store_init_failed", error=str(e))

    # ---------- 1. 沙箱 + 代码库分析（并行） ----------
    t_parallel = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        sandbox_future = ex.submit(_start_sandbox, cfg, log)
        codebase_future = ex.submit(_build_codebase, cfg, log)

        sandbox, sandbox_from_pool = sandbox_future.result()
        parser, dep_graph, call_graph, analyzer = codebase_future.result()

    log.info("parallel_init_done", elapsed_s=round(time.time() - t_parallel, 2))

    # ---------- 2. 状态栏 ----------
    status_bar = AgentStatusBar(mode="persistent")

    # ---------- 3. 全局绑定 ----------
    bind_sandbox(sandbox)
    bind_tx(sandbox, str(cfg.project_path))
    bind_context(str(cfg.project_path))
    bind_test(sandbox)
    bind_status(status_bar)
    bind_subagent(str(cfg.project_path), cfg.model)
    bind_graphs(call_graph)

    # P1-2: Reviewer 初始化 + 绑定
    reviewer_llm = _build_reviewer_llm(cfg)
    reviewer = Reviewer(reviewer_llm)
    bind_review(sandbox, reviewer)
    log.info(
        "reviewer_ready",
        model=os.getenv("AGENT_REVIEWER_MODEL", cfg.model),
    )

    # P1-3: 报告工具绑定
    report_dir = cfg.meta_dir / "reports"
    bind_report(sandbox, report_dir)
    log.info("report_bind_ready", dir=str(report_dir))

    # P2: 经验归档存储
    evolution_store = EvolutionStore(cfg.meta_dir / "evolution")
    set_store(evolution_store)
    log.info(
        "evolution_store_ready",
        path=str(evolution_store.experiences_path),
    )

    # ★ P3: 并行执行器占位（等工具池构造完再实际创建）
    parallel_executor_holder: dict[str, Any] = {}

    # ---------- 4. 后台索引 ----------
    indexer = CodeIndexer(parser, persist_dir=str(cfg.index_dir))
    bg_indexer = BackgroundIndexer(parser, indexer)
    bg_indexer.start(background=True)

    # ---------- 5. 技能 ----------
    skill_registry = SkillRegistry()
    status_bar.set_skills([s.name for s in skill_registry.all_skills()])

    # ---------- 6. MCP ----------
    enable_mcp = cfg.enable_mcp
    if eval_mode and not _env_bool("AGENT_FORCE_MCP_IN_EVAL", "false"):
        enable_mcp = False

    mcp_tools: list[Any] = []
    mcp_server_to_tools: dict[str, list[str]] = {}
    mcp_auto_expose: list[str] = []

    if enable_mcp and _MCP_AVAILABLE:
        try:
            mcp_config = build_mcp_config(cfg.agent_home, cfg.project_path)
            mcp_auto_expose = list(getattr(mcp_config, "auto_expose", []) or [])

            mcp_timeout = _env_float("AGENT_MCP_TIMEOUT", 60.0)
            mcp_tools, tool_to_server = _load_mcp_in_thread_with_mapping(
                mcp_config, timeout=mcp_timeout
            )

            mcp_server_to_tools = _aggregate_server_to_tools(
                mcp_tools,
                tool_to_server,
                list(mcp_config.servers.keys()),
            )

            log.info(
                "mcp_tools_loaded",
                total=len(mcp_tools),
                servers={s: len(ts) for s, ts in sorted(mcp_server_to_tools.items())},
                auto_expose=mcp_auto_expose or None,
            )
        except Exception as e:
            log.warning("mcp_load_failed", error=str(e))
    else:
        if not _MCP_AVAILABLE:
            log.info("mcp_skipped", reason="mcp_client.client 未找到")
        else:
            log.info("mcp_skipped", reason="AGENT_ENABLE_MCP=false")

    # ---------- 7. 工具集 ----------
    tools: list[Any] = []

    tools += build_default_tools(str(cfg.project_path))

    from tools import sandbox_ops as _sb

    tools += [_sb.__dict__[n] for n in SANDBOX_TOOLS]

    from tools import transaction_ops as _tx

    tools += [_tx.__dict__[n] for n in TRANSACTION_TOOLS]

    tools.append(create_apply_patch_tool(str(cfg.project_path)))

    tools += [
        create_repo_map_tool(RepoMapBuilder(parser)),
        create_search_tool(bg_indexer),
        create_index_status_tool(bg_indexer),
        *create_dep_tools(dep_graph),
        *create_call_tools(call_graph),
        create_impact_tool(analyzer),
    ]

    from tools import context_ops as _ctx

    tools += [_ctx.__dict__[n] for n in CONTEXT_TOOLS]

    from tools import test_ops as _test

    tools += [_test.__dict__[n] for n in TEST_TOOLS]

    from tools import status_ops as _st

    tools += [_st.__dict__[n] for n in STATUS_TOOLS]

    from tools import subagent_ops as _sub

    tools += [_sub.__dict__[n] for n in SUBAGENT_TOOLS]

    # P1-2: Reviewer 工具
    from tools import review_ops as _rv

    tools += [_rv.__dict__[n] for n in REVIEW_TOOLS]

    # P1-3: 报告工具
    from tools import report_ops as _rp

    tools += [_rp.__dict__[n] for n in REPORT_TOOLS]

    # ★ P3: 并行 Worker 工具
    from tools import parallel_ops as _par

    tools += [_par.__dict__[n] for n in PARALLEL_TOOLS]

    tools.append(create_load_skill_tool(skill_registry))

    # ---------- 7.1 MCP 元工具（渐进式披露） ----------
    _filter_holder: dict[str, Any] = {}

    def _on_use_server(server_name: str) -> bool:
        tf = _filter_holder.get("middleware")
        if tf is None:
            log.warning("mcp_reveal_failed", server=server_name, reason="tool_filter 未注册")
            return False
        ok = tf.expose_mcp_server(server_name)
        if not ok:
            log.warning("mcp_reveal_failed", server=server_name, reason="未知 server")
        else:
            log.info("mcp_server_revealed", server=server_name)
        return ok

    if mcp_server_to_tools:
        try:
            from mcp_client.discovery import create_mcp_meta_tools

            mcp_meta_tools = create_mcp_meta_tools(
                server_to_tools=mcp_server_to_tools,
                on_use_server=_on_use_server,
            )
            tools += mcp_meta_tools
            log.info(
                "mcp_meta_tools_registered",
                servers=len(mcp_server_to_tools),
            )
        except ImportError as e:
            log.warning("mcp_meta_tools_load_failed", error=str(e))

    # ---------- 7.2 完整工具池 ----------
    all_tools_pool: list[Any] = list(tools) + list(mcp_tools)
    all_tools_pool = sorted(all_tools_pool, key=lambda t: t.name)
    all_tools_pool.append(create_tool_search_tool(all_tools_pool))

    validate_tools(all_tools_pool, strict=cfg.strict_lint)

    # ---------- 8. 系统提示 ----------
    system_prompt = load_system_prompt(cfg.agent_home)

    project_memory = load_project_memory(cfg.project_path)
    if project_memory:
        system_prompt = f"{system_prompt}\n\n## Project Memory\n{project_memory}"

    user_memory_enabled = _env_bool("AGENT_USER_MEMORY", "true")
    if eval_mode:
        user_memory_enabled = _env_bool("AGENT_USER_MEMORY", "false")

    if user_memory_enabled:
        try:
            max_cards = _env_int("AGENT_USER_MEMORY_MAX_CARDS", 40)
            cards_text = user_card_repo().render_prompt(max_cards=max_cards)
            if cards_text:
                system_prompt = f"{system_prompt}\n\n## 用户记忆\n{cards_text}"
        except Exception as e:
            log.warning("user_cards_inject_failed", error=str(e))

    skill_meta = skill_registry.metadata_prompt()
    if skill_meta:
        system_prompt = f"{system_prompt}\n\n{skill_meta}"

    # ---------- 9. 上下文装配 ----------
    assembler = ContextAssembler(
        system_prompt=system_prompt,
        tool_definitions=render_tool_definitions(all_tools_pool),
        project_memory="",
    )

    # ---------- 10. 轨迹持久化 ----------
    trajectory_writer: TrajectoryWriter | None = None
    trajectory_mw: TrajectoryMiddleware | None = None
    if not eval_mode:
        from datetime import datetime

        session_id = (
            f"session-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid() & 0xFFFF:04x}"
        )
        trajectory_writer = TrajectoryWriter(
            session_id=session_id,
            base_dir=str(cfg.trajectory_dir),
        )
        trajectory_mw = TrajectoryMiddleware(trajectory_writer)
        log.info(
            "trajectory_writer_ready",
            session_id=session_id,
            path=str(trajectory_writer.path),
        )

    # ---------- 11. 指标队列 ----------
    metrics_queue: "queue.Queue[dict]" = queue.Queue(maxsize=2000)

    def _on_metric(event: dict) -> None:
        try:
            metrics_queue.put_nowait(event)
        except queue.Full:
            pass

    from observability.metrics_store import MetricsStore

    metrics_store = MetricsStore(str(Path.home() / ".coding-agent" / "metrics.db"))

    # ---------- 12. 中间件链 ----------
    skill_tool_map = {s.name: s.tools for s in skill_registry.all_skills()}

    circuit_breaker = CircuitBreakerMiddleware(
        CircuitBreakerConfig(
            read_only_max_repeats=_env_int("AGENT_CB_READ_REPEATS", 20),
            write_max_repeats=_env_int("AGENT_CB_WRITE_REPEATS", 5),
            default_max_repeats=_env_int("AGENT_CB_DEFAULT_REPEATS", 8),
            max_consecutive_failures=_env_int("AGENT_CB_MAX_FAILURES", 3),
            max_retries_for_retryable=_env_int("AGENT_CB_MAX_RETRIES", 5),
        )
    )

    tool_filter_mw = create_tool_filter_middleware(
        [t.name for t in all_tools_pool],
        skill_tool_map,
        mcp_server_to_tools=mcp_server_to_tools,
        auto_expose_servers=mcp_auto_expose,
    )

    _filter_holder["middleware"] = tool_filter_mw

    # P1-1: 自动测试
    auto_test_mw = AutoTestMiddleware(
        test_command=os.getenv(
            "AGENT_AUTO_TEST_COMMAND", "pytest tests/ -v --tb=short"
        ),
        enabled=_env_bool("AGENT_AUTO_TEST", "true"),
        cooldown_s=_env_float("AGENT_AUTO_TEST_COOLDOWN", 3.0),
    )

    thinking_router_default = "false" if eval_mode else "true"
    retrieval_default = "false" if eval_mode else "true"

    middlewares = [
        create_thinking_router_middleware(
            provider=cfg.provider_id,
            enabled=_env_bool("AGENT_THINKING_ROUTER", thinking_router_default),
            strategy=os.getenv("AGENT_THINKING_STRATEGY", "auto"),
        ),
        create_content_stripper_middleware(
            enabled=_env_bool("AGENT_CONTENT_STRIPPER", "true"),
        ),
        create_retrieval_inject_middleware(
            enabled=_env_bool("AGENT_RETRIEVAL", retrieval_default),
            top_k=_env_int("AGENT_RETRIEVAL_TOP_K", 3),
        ),
        create_idempotency_middleware(
            enabled=_env_bool("AGENT_IDEMPOTENCY", "true"),
        ),
        ContextCompactionMiddleware(
            model=compaction_llm,
            workspace=str(cfg.project_path),
            config=CompactionPipelineConfig(model_window=cfg.model_window),
        ),
        tool_filter_mw,
        MetricsMiddleware(
            store=metrics_store,
            model_name=cfg.model,
            debug=False,
            on_metric=_on_metric,
        ),
        create_dependency_check_middleware(analyzer),
        circuit_breaker,
        *([] if eval_mode else [StatusBarMiddleware(status_bar)]),
        auto_test_mw,
        *([] if trajectory_mw is None else [trajectory_mw]),
        create_prompt_cache_middleware(
            cache_ttl="5m",
            default_cache_key="coding-agent-v1",
            model_provider=cfg.model_provider,
        ),
    ]

    # ---------- 13. 组装 Agent ----------
    agent = create_agent(
        model=llm,
        tools=all_tools_pool,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=checkpointer,
    )

    # ---------- 13.1 P1-1: 注入 run_tests 到 auto_test_mw ----------
    try:
        run_tests_tool = next(
            (t for t in all_tools_pool if t.name == "run_tests"), None
        )
        if run_tests_tool is not None:
            auto_test_mw.bind_run_tests_tool(run_tests_tool)
            log.info("auto_test_mw_bound", tool="run_tests")
        else:
            log.warning("auto_test_mw_bind_failed", reason="run_tests 未找到")
    except Exception as e:
        log.warning("auto_test_mw_bind_failed", error=str(e))

    # ---------- 13.2 ★ P3: 创建并行执行器 ----------
    parallel_executor: ParallelExecutor | None = None
    try:
        parallel_executor = ParallelExecutor(
            llm=llm,
            sandbox=sandbox,
            base_dir=cfg.meta_dir / "parallel",
            tools=all_tools_pool,
            max_workers=_env_int("AGENT_PARALLEL_MAX_WORKERS", 3),
            max_iterations=_env_int("AGENT_PARALLEL_MAX_ITER", 15),
        )
        set_executor(parallel_executor)
        parallel_executor_holder["executor"] = parallel_executor
        log.info(
            "parallel_executor_ready",
            max_workers=parallel_executor.max_workers,
            shared_dir=str(parallel_executor.shared_dir),
        )
    except Exception as e:
        log.warning("parallel_executor_failed", error=str(e))

    # ---------- 14. 日志 ----------
    backend_info = store_backend_info()
    sandbox_settings = SandboxSettings.from_env()

    log.info(
        "agent_build_done",
        tools_total=len(all_tools_pool),
        mcp_tools=len(mcp_tools),
        mcp_servers=len(mcp_server_to_tools),
        mcp_auto_expose=len(mcp_auto_expose),
        skills=len(skill_registry.all_skills()),
        eval_mode=eval_mode,
        thinking_router=_env_bool("AGENT_THINKING_ROUTER", thinking_router_default),
        content_stripper=_env_bool("AGENT_CONTENT_STRIPPER", "true"),
        retrieval=_env_bool("AGENT_RETRIEVAL", retrieval_default),
        idempotency=_env_bool("AGENT_IDEMPOTENCY", "true"),
        user_memory=user_memory_enabled,
        memory_backend=backend_info.get("backend", "?"),
        memory_type=backend_info.get("type", "?"),
        sandbox_network=sandbox_settings.network,
        sandbox_memory=sandbox_settings.memory_limit,
        checkpoint_db=str(cfg.meta_dir / "sessions" / "checkpoints.db"),
        parallel_executor=parallel_executor is not None,
        elapsed_s=round(time.time() - t0, 2),
    )

    # ---------- 15. 返回运行时 ----------
    return AgentRuntime(
        agent=agent,
        sandbox=sandbox,
        assembler=assembler,
        tools=all_tools_pool,
        bg_indexer=bg_indexer,
        config=cfg,
        skill_registry=skill_registry,
        status_bar=status_bar,
        circuit_breaker=circuit_breaker,
        trajectory_writer=trajectory_writer,
        metrics_queue=metrics_queue,
        checkpointer=checkpointer,
        sandbox_from_pool=sandbox_from_pool,
        evolution_store=evolution_store,
        parallel_executor=parallel_executor,
    )
