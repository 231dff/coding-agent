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
from codebase.background_indexer import BackgroundIndexer
from codebase.call_graph import CallGraph, create_call_tools
from codebase.dep_graph import DependencyGraph, create_dep_tools
from codebase.impact import ImpactAnalyzer, create_impact_tool
from codebase.indexer import (
    CodeIndexer,
    create_index_status_tool,
    create_search_tool,
)

# ---------- 代码库分析 ----------
from codebase.parser import CodeParser
from codebase.repo_map import RepoMapBuilder, create_repo_map_tool

# ---------- 上下文 ----------
from context.assembly import ContextAssembler
from context.status_bar import AgentStatusBar

# ---------- 记忆 ----------
from memory.cards import user_card_repo
from memory.store import (
    get_store as get_memory_store,
)
from memory.store import (
    store_backend_info,
)
from middleware.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerMiddleware,
)
from middleware.content_stripper import create_content_stripper_middleware
from middleware.context_compaction import (
    CompactionPipelineConfig,
    ContextCompactionMiddleware,
)

# ---------- 中间件 ----------
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

# ---------- 可观测性 ----------
from observability.trajectory_writer import TrajectoryWriter

# ---------- 沙箱 ----------
from sandbox.docker_backend import DockerSandbox
from sandbox.patch import create_apply_patch_tool
from sandbox.pool import SandboxPool
from skills.loader import create_load_skill_tool

# ---------- 技能 ----------
from skills.registry import SkillRegistry
from tools.context_ops import CONTEXT_TOOLS
from tools.context_ops import bind as bind_context
from tools.lint import validate_tools

# ---------- 工具 ----------
from tools.registry import build_default_tools
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

# ---------- MCP ----------
try:
    from mcp_client.client import MCPConfig, load_mcp_tools_sync

    _MCP_AVAILABLE = True
except ImportError as _e:
    import sys

    print(f"[core] MCP 导入失败: {_e}", file=sys.stderr)
    MCPConfig = None  # type: ignore
    load_mcp_tools_sync = None  # type: ignore
    _MCP_AVAILABLE = False


# ============================================================
# 环境变量开关（评测/精简模式用）
# ============================================================


def _env_bool(key: str, default: str = "true") -> bool:
    """读布尔环境变量。"""
    return os.getenv(key, default).lower() == "true"


def _is_eval_mode() -> bool:
    """评测模式：关闭所有非必要中间件，最小化 token 和启动开销。

    开启方式：设置 AGENT_EVAL_MODE=true
    """
    return _env_bool("AGENT_EVAL_MODE", "false")


# ============================================================
# 全局沙箱工厂（进程级单例）
# ============================================================

_SANDBOX_POOL: SandboxPool | None = None
_SANDBOX_POOL_LOCK = threading.Lock()


def _get_sandbox_pool() -> SandboxPool:
    """返回进程级沙箱工厂。"""
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
    """加载系统提示词。

    评测模式下优先使用 prompts/system_minimal.md（若存在）。
    """
    if _is_eval_mode():
        minimal = agent_home / "prompts" / "system_minimal.md"
        if minimal.exists():
            return minimal.read_text(encoding="utf-8")

    path = agent_home / "prompts" / "system_v1.md"
    if not path.exists():
        raise FileNotFoundError(f"系统提示词文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def load_project_memory(project_path: Path) -> str:
    """加载项目记忆（从用户项目里读取，启动时读一次）。"""
    if _is_eval_mode():
        return ""
    for name in ("AGENTS.md", "CLAUDE.md", "CODING_AGENT.md"):
        p = project_path / name
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def render_tool_definitions(tools: list[Any]) -> str:
    """渲染工具定义为字母序排列的稳定文本（用于前缀哈希校验）。"""
    lines = []
    for t in sorted(tools, key=lambda x: x.name):
        desc = (t.description or "").split("\n", 1)[0].strip()
        lines.append(f"- {t.name}: {desc}")
    return "\n".join(lines)


def build_mcp_config(agent_home: Path):
    """构建 MCP Server 配置。"""
    if not _MCP_AVAILABLE:
        raise RuntimeError("MCP 不可用（mcp_client.client 导入失败）")

    return MCPConfig(
        servers={
            "git": {
                "command": "python",
                "args": [str(agent_home / "mcp_client" / "servers" / "git_server.py")],
                "transport": "stdio",
            },
            "web": {
                "command": "python",
                "args": [str(agent_home / "mcp_client" / "servers" / "web_search_server.py")],
                "transport": "stdio",
            },
        }
    )


def _load_mcp_in_thread(config, timeout: float = 15.0) -> list[Any]:
    """在独立线程里加载 MCP，超时或失败返回空，不阻塞启动。"""
    if load_mcp_tools_sync is None:
        return []

    def _run():
        return load_mcp_tools_sync(config)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_run)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print(f"[core] MCP 加载超时（{timeout}s），降级为无 MCP 工具")
            return []
        except Exception as e:
            print(f"[core] MCP 加载失败: {e}")
            return []


# ============================================================
# LLM 初始化（多 Provider + temperature 可选）
# ============================================================


def build_llm(cfg: AgentConfig):
    """初始化 LLM。"""
    # ---------- Anthropic 原生接口 ----------
    if cfg.model_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        print(f"[core] Anthropic 接口: provider={cfg.provider_id!r} model={cfg.model!r}")

        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "api_key": cfg.api_key,
            "timeout": cfg.timeout,
            "max_retries": 2,
        }
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature

        return ChatAnthropic(**kwargs)

    # ---------- OpenAI 兼容接口 ----------
    from langchain_openai import ChatOpenAI

    print(
        f"[core] OpenAI 兼容接口: provider={cfg.provider_id!r} "
        f"model={cfg.model!r} base_url={cfg.base_url!r}"
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
    """压缩用轻量模型：优先环境变量 AGENT_COMPACTION_MODEL，其次主模型。"""
    cheap_model = os.getenv("AGENT_COMPACTION_MODEL", "")
    if not cheap_model:
        return build_llm(cfg)

    from copy import replace

    try:
        cheap_cfg = replace(cfg, model=cheap_model)
        return build_llm(cheap_cfg)
    except Exception:
        return build_llm(cfg)


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

    _planning_graph: Any = field(default=None, init=False, repr=False)
    _repair_graph: Any = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    # ---------- 转发到底层 agent ----------

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

    # ---------- 懒加载图 ----------

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

    # ---------- 生命周期 ----------

    def close(self) -> None:
        """释放资源。"""
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

    # ---------- 状态查询 ----------

    def check_prefix_stability(self) -> bool:
        return self.assembler.check_prefix_stability()

    def index_ready(self) -> bool:
        return self.bg_indexer.is_ready()


# ============================================================
# 并行辅助
# ============================================================


def _start_sandbox(cfg: AgentConfig, log) -> tuple[DockerSandbox, bool]:
    """启动沙箱。返回 (sandbox, from_pool)。"""
    from_pool = False
    try:
        sb = _get_sandbox_pool().acquire(str(cfg.project_path))
        from_pool = True
        return sb, from_pool
    except Exception as e:
        log.warning("sandbox_factory_acquire_failed", error=str(e))
        sb = DockerSandbox(
            str(cfg.project_path),
            memory_limit="2g",
            cpu_limit=2.0,
            network=False,
        )
        sb.start()
        return sb, from_pool


def _build_codebase(cfg: AgentConfig, log) -> tuple[Any, Any, Any, Any]:
    """构建代码库分析对象。"""
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
    """组装完整的 Coding Agent。

    性能优化：
    - 沙箱启动与代码库分析并行
    - 评测模式（AGENT_EVAL_MODE=true）会跳过 memory / retrieval / status_bar /
      trajectory / 用户卡片注入，最小化 token 和启动开销
    """
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

    # ---------- 0. LLM + checkpointer（快） ----------
    llm = build_llm(cfg)
    compaction_llm = _build_compaction_llm(cfg)
    checkpointer = build_checkpointer(cfg.meta_dir)

    # Memory store 首次初始化（评测模式跳过，避免加载嵌入模型）
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

    log.info(
        "parallel_init_done",
        elapsed_s=round(time.time() - t_parallel, 2),
    )

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
    if enable_mcp and _MCP_AVAILABLE:
        try:
            mcp_config = build_mcp_config(cfg.agent_home)
            mcp_tools = _load_mcp_in_thread(mcp_config, timeout=15.0)
            print(f"[core] MCP 工具加载成功: {len(mcp_tools)} 个")
        except Exception as e:
            log.warning("mcp_load_failed", error=str(e))
    else:
        if not _MCP_AVAILABLE:
            print("[core] MCP 已跳过（mcp_client.client 未找到）")
        else:
            print("[core] MCP 已跳过（AGENT_ENABLE_MCP=false）")

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

    tools.append(create_load_skill_tool(skill_registry))
    tools += mcp_tools

    tools = sorted(tools, key=lambda t: t.name)
    tools.append(create_tool_search_tool(tools))

    validate_tools(tools, strict=cfg.strict_lint)

    # ---------- 8. 系统提示 ----------
    system_prompt = load_system_prompt(cfg.agent_home)

    project_memory = load_project_memory(cfg.project_path)
    if project_memory:
        system_prompt = f"{system_prompt}\n\n## Project Memory\n{project_memory}"

    # 第 1 层记忆：用户卡片（全量注入）
    user_memory_enabled = _env_bool("AGENT_USER_MEMORY", "true")
    if eval_mode:
        user_memory_enabled = _env_bool("AGENT_USER_MEMORY", "false")

    if user_memory_enabled:
        try:
            max_cards = int(os.getenv("AGENT_USER_MEMORY_MAX_CARDS", "40"))
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
        tool_definitions=render_tool_definitions(tools),
        project_memory="",
    )

    # ---------- 10. 轨迹持久化 ----------
    trajectory_writer: TrajectoryWriter | None = None
    trajectory_mw: TrajectoryMiddleware | None = None
    if not eval_mode:
        trajectory_writer = TrajectoryWriter(
            session_id=f"session-{id(cfg) & 0xFFFFFF:x}",
            base_dir=str(cfg.trajectory_dir),
        )
        trajectory_mw = TrajectoryMiddleware(trajectory_writer)

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
    all_tool_names = [t.name for t in tools]
    skill_tool_map = {s.name: s.tools for s in skill_registry.all_skills()}

    # ★ 熔断器：只读工具阈值 20，写工具阈值 5，未知工具阈值 8
    circuit_breaker = CircuitBreakerMiddleware(
        CircuitBreakerConfig(
            read_only_max_repeats=int(os.getenv("AGENT_CB_READ_REPEATS", "20")),
            write_max_repeats=int(os.getenv("AGENT_CB_WRITE_REPEATS", "5")),
            default_max_repeats=int(os.getenv("AGENT_CB_DEFAULT_REPEATS", "8")),
            max_consecutive_failures=int(os.getenv("AGENT_CB_MAX_FAILURES", "3")),
            max_retries_for_retryable=int(os.getenv("AGENT_CB_MAX_RETRIES", "5")),
        )
    )

    # 评测模式下的开关默认值
    thinking_router_default = "false" if eval_mode else "true"
    retrieval_default = "false" if eval_mode else "true"

    middlewares = [
        # 1. 条件化思考（最先跑，读原始 user 消息）
        create_thinking_router_middleware(
            provider=cfg.provider_id,
            enabled=_env_bool("AGENT_THINKING_ROUTER", thinking_router_default),
            strategy=os.getenv("AGENT_THINKING_STRATEGY", "auto"),
        ),
        # 2. Content 剥离
        create_content_stripper_middleware(
            enabled=_env_bool("AGENT_CONTENT_STRIPPER", "true"),
        ),
        # 3. 第 2 层记忆：检索注入
        create_retrieval_inject_middleware(
            enabled=_env_bool("AGENT_RETRIEVAL", retrieval_default),
            top_k=int(os.getenv("AGENT_RETRIEVAL_TOP_K", "3")),
        ),
        # 4. 幂等性保护
        create_idempotency_middleware(
            enabled=_env_bool("AGENT_IDEMPOTENCY", "true"),
        ),
        # 5. 上下文压缩
        ContextCompactionMiddleware(
            model=compaction_llm,
            workspace=str(cfg.project_path),
            config=CompactionPipelineConfig(model_window=cfg.model_window),
        ),
        # 6. 工具过滤（按激活的 skill + search_tools 结果）
        create_tool_filter_middleware(all_tool_names, skill_tool_map),
        # 7. 指标采集
        MetricsMiddleware(
            store=metrics_store,
            model_name=cfg.model,
            debug=False,
            on_metric=_on_metric,
        ),
        # 8. 依赖检查
        create_dependency_check_middleware(analyzer),
        # 9. 熔断器（新阈值策略）
        circuit_breaker,
        # 10. 状态栏注入（评测模式跳过）
        *([] if eval_mode else [StatusBarMiddleware(status_bar)]),
        # 11. 轨迹持久化（评测模式跳过）
        *([] if trajectory_mw is None else [trajectory_mw]),
        # 12. 缓存标记
        create_prompt_cache_middleware(
            cache_ttl="5m",
            default_cache_key="coding-agent-v1",
            model_provider=cfg.model_provider,
        ),
    ]

    # ---------- 13. 组装 Agent ----------
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=checkpointer,
    )

    # ---------- 14. 日志 ----------
    backend_info = store_backend_info()

    log.info(
        "agent_build_done",
        tools=len(tools),
        skills=len(skill_registry.all_skills()),
        mcp_tools=len(mcp_tools),
        eval_mode=eval_mode,
        thinking_router=_env_bool("AGENT_THINKING_ROUTER", thinking_router_default),
        content_stripper=_env_bool("AGENT_CONTENT_STRIPPER", "true"),
        retrieval=_env_bool("AGENT_RETRIEVAL", retrieval_default),
        idempotency=_env_bool("AGENT_IDEMPOTENCY", "true"),
        user_memory=user_memory_enabled,
        memory_backend=backend_info.get("backend", "?"),
        memory_type=backend_info.get("type", "?"),
        checkpoint_db=str(cfg.meta_dir / "sessions" / "checkpoints.db"),
        elapsed_s=round(time.time() - t0, 2),
    )

    # ---------- 15. 返回运行时 ----------
    return AgentRuntime(
        agent=agent,
        sandbox=sandbox,
        assembler=assembler,
        tools=tools,
        bg_indexer=bg_indexer,
        config=cfg,
        skill_registry=skill_registry,
        status_bar=status_bar,
        circuit_breaker=circuit_breaker,
        trajectory_writer=trajectory_writer,
        metrics_queue=metrics_queue,
        checkpointer=checkpointer,
        sandbox_from_pool=sandbox_from_pool,
    )
