"""agent/core.py — Coding Agent 装配入口。

核心设计：
- agent_home:   Agent 自身代码路径（只读，加载 prompts/queries）
- project_path: 用户项目路径（Agent 操作对象）
- meta_dir:     Agent 元数据目录（用户项目内的 .coding-agent/）

集成：
- 多 Provider 模型支持（Qwen / OpenAI / Anthropic / DeepSeek / Moonshot /
  智谱 / Gemini / OpenRouter / Ollama / 自定义）
- P0-1 Agent 状态栏
- P0-2 故障分类 + 熔断器
- P1-1 子 Agent 委派搜索
- P1-2 上下文感知压缩
- P2-1 工具描述 Lint
- P2-2 轨迹持久化
- 指标采集（MetricsMiddleware + SSE 事件推送）

兼容性：
- temperature 为 None 时不发送该参数（兼容 kimi-k3、deepseek-reasoner、o1 等）
- api_key 为空时用 "dummy" 占位（兼容 Ollama 等本地端点）

缓存友好设计：
- ChatOpenAI 设置 prompt_cache_key，让服务端识别会话前缀
- 中间件顺序：压缩 → 过滤 → 指标 → 工具层 → 状态栏 → 轨迹 → 缓存标记
- 工具集按字母序排序，保证工具定义块稳定
- 状态栏移除时间戳类字段
"""
from __future__ import annotations

import concurrent.futures
import queue                                            # ← 改动：新增 queue 导入
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import AgentConfig

# ---------- 沙箱 ----------
from sandbox.docker_backend import DockerSandbox
from sandbox.patch import create_apply_patch_tool

# ---------- 工具 ----------
from tools.registry import build_default_tools
from tools.sandbox_ops import bind as bind_sandbox, SANDBOX_TOOLS
from tools.transaction_ops import bind as bind_tx, TRANSACTION_TOOLS
from tools.context_ops import bind as bind_context, CONTEXT_TOOLS
from tools.test_ops import bind as bind_test, TEST_TOOLS
from tools.status_ops import bind as bind_status, STATUS_TOOLS
from tools.subagent_ops import bind as bind_subagent, SUBAGENT_TOOLS
from tools.lint import validate_tools

# ---------- 代码库分析 ----------
from codebase.parser import CodeParser
from codebase.dep_graph import DependencyGraph, create_dep_tools
from codebase.call_graph import CallGraph, create_call_tools
from codebase.impact import ImpactAnalyzer, create_impact_tool
from codebase.repo_map import RepoMapBuilder, create_repo_map_tool
from codebase.indexer import (
    CodeIndexer,
    create_search_tool,
    create_index_status_tool,
)
from codebase.background_indexer import BackgroundIndexer

# ---------- 中间件 ----------
from middleware.dependency_check import create_dependency_check_middleware
from middleware.prompt_cache import create_prompt_cache_middleware
from middleware.context_compaction import (
    ContextCompactionMiddleware,
    CompactionPipelineConfig,
)
from middleware.tool_filter import create_tool_filter_middleware
from middleware.tool_search import create_tool_search_tool
from middleware.status_bar import StatusBarMiddleware
from middleware.circuit_breaker import CircuitBreakerMiddleware, CircuitBreakerConfig
from middleware.trajectory import TrajectoryMiddleware
from middleware.metrics import MetricsMiddleware

# ---------- 上下文 ----------
from context.assembly import ContextAssembler
from context.status_bar import AgentStatusBar

# ---------- 可观测性 ----------
from observability.trajectory_writer import TrajectoryWriter

# ---------- 技能 ----------
from skills.registry import SkillRegistry
from skills.loader import create_load_skill_tool

# ---------- 任务规划与修复 ----------
from agent.graph import build_planning_graph
from agent.test_loop import build_repair_graph

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
# 资源加载
# ============================================================

def load_system_prompt(agent_home: Path) -> str:
    """加载六段式系统提示词（从 Agent 自身目录读取）。"""
    path = agent_home / "prompts" / "system_v1.md"
    if not path.exists():
        raise FileNotFoundError(f"系统提示词文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def load_project_memory(project_path: Path) -> str:
    """加载项目记忆（从用户项目里读取）。"""
    for name in ("AGENTS.md", "CLAUDE.md", "CODING_AGENT.md"):
        p = project_path / name
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def render_tool_definitions(tools: list[Any]) -> str:
    """渲染工具定义为**字母序**排列的稳定文本（用于前缀哈希校验）。"""
    lines = []
    for t in sorted(tools, key=lambda x: x.name):
        desc = (t.description or "").split("\n", 1)[0].strip()
        lines.append(f"- {t.name}: {desc}")
    return "\n".join(lines)


def build_mcp_config(agent_home: Path):
    """构建 MCP Server 配置（MCP Server 脚本在 Agent 自身目录）。"""
    if not _MCP_AVAILABLE:
        raise RuntimeError("MCP 不可用（mcp_client.client 导入失败）")

    return MCPConfig(servers={
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
    })


def _load_mcp_in_thread(config) -> list[Any]:
    """在独立线程里调用同步版 MCP 加载器，避免 asyncio 事件循环冲突。"""
    def _run():
        return load_mcp_tools_sync(config)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_run)
        return future.result(timeout=30)


# ============================================================
# LLM 初始化（多 Provider + temperature 可选）
# ============================================================

def build_llm(cfg: AgentConfig):
    """初始化 LLM。

    temperature 为 None 时不发送该参数——某些模型（如 kimi-k3、
    deepseek-reasoner、o1）不接受 temperature，会返回 400。

    根据 cfg.model_provider 选择客户端：
    - anthropic: ChatAnthropic（原生接口）
    - openai:    ChatOpenAI（兼容 Qwen / DeepSeek / Moonshot / 智谱 /
                 Gemini / OpenRouter / Ollama / 自定义端点）
    """
    # ---------- Anthropic 原生接口 ----------
    if cfg.model_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        print(
            f"[core] Anthropic 接口: provider={cfg.provider_id!r} "
            f"model={cfg.model!r}"
        )
        if cfg.temperature is None:
            print("[core] temperature: (不发送)")
        else:
            print(f"[core] temperature: {cfg.temperature}")

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
    if cfg.temperature is None:
        print("[core] temperature: (不发送)")
    else:
        print(f"[core] temperature: {cfg.temperature}")

    kwargs: dict[str, Any] = {
        "model": cfg.model,
        # Ollama 等本地端点不需要 key，但 SDK 要求非空
        "api_key": cfg.api_key or "dummy",
        "max_retries": 2,
        "timeout": cfg.timeout,
        # 关键：prompt_cache_key 让服务端识别会话前缀
        "model_kwargs": {
            "prompt_cache_key": "coding-agent-v1",
        },
    }
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url

    llm = ChatOpenAI(**kwargs)

    actual_model = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    print(f"[core] 实际发送的模型名: {actual_model!r}")
    print(
        f"[core] prompt_cache_key: "
        f"{llm.model_kwargs.get('prompt_cache_key', '(none)')!r}"
    )

    return llm


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
    planning_graph: Any = None
    repair_graph: Any = None
    status_bar: AgentStatusBar | None = None
    circuit_breaker: CircuitBreakerMiddleware | None = None
    trajectory_writer: TrajectoryWriter | None = None
    metrics_queue: Any = None          # ← 改动：供 SSE 消费的指标事件队列
    _closed: bool = field(default=False, init=False)

    def close(self) -> None:
        """释放资源。"""
        if self._closed:
            return
        self._closed = True
        try:
            self.bg_indexer.stop(timeout=5.0)
        except Exception:
            pass
        try:
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
# 主装配函数
# ============================================================

def build_agent(cfg: AgentConfig) -> AgentRuntime:
    """组装完整的 Coding Agent。

    关键路径分离：
    - cfg.agent_home     → 加载 prompts/queries/MCP Server
    - cfg.project_path   → 沙箱挂载、代码索引、文件操作
    - cfg.meta_dir       → 索引、轨迹、记忆等元数据
    """
    # ← 改动：开头初始化 logger
    from observability.logger import get_logger
    log = get_logger("core")

    cfg.validate()
    log.info(
        "agent_build_start",
        provider=cfg.provider_id,
        model=cfg.model,
        project=str(cfg.project_path),
    )

    # ---------- 0. 初始化 LLM ----------
    print(f"[core] 配置: {cfg.to_dict()}")
    llm = build_llm(cfg)

    # ---------- 1. 沙箱挂载用户项目 ----------
    sandbox = DockerSandbox(
        str(cfg.project_path),
        memory_limit="2g",
        cpu_limit=2.0,
        network=False,
    )
    sandbox.start()

    # ---------- 2. 代码库静态分析（指向用户项目）----------
    parser = CodeParser(str(cfg.project_path))
    dep_graph = DependencyGraph(parser)
    dep_graph.build()
    call_graph = CallGraph(parser)
    call_graph.build()
    analyzer = ImpactAnalyzer(call_graph, dep_graph)

    # ---------- 3. 状态栏 ----------
    status_bar = AgentStatusBar(mode="persistent")

    # ---------- 4. 全局绑定 ----------
    bind_sandbox(sandbox)
    bind_tx(sandbox, str(cfg.project_path))
    bind_context(str(cfg.project_path))
    bind_test(sandbox)
    bind_status(status_bar)
    bind_subagent(str(cfg.project_path), cfg.model)

    # ---------- 5. 后台索引 ----------
    indexer = CodeIndexer(
        parser,
        persist_dir=str(cfg.index_dir),
    )
    bg_indexer = BackgroundIndexer(parser, indexer)
    bg_indexer.start(background=True)

    # ---------- 6. 技能 ----------
    skill_registry = SkillRegistry()
    status_bar.set_skills([s.name for s in skill_registry.all_skills()])

    # ---------- 7. MCP ----------
    mcp_tools: list[Any] = []
    if cfg.enable_mcp and _MCP_AVAILABLE:
        try:
            mcp_config = build_mcp_config(cfg.agent_home)
            mcp_tools = _load_mcp_in_thread(mcp_config)
            print(f"[core] MCP 工具加载成功: {len(mcp_tools)} 个")
        except Exception as e:
            print(f"[warn] MCP 加载失败，降级为无 MCP 工具: {e}")
    else:
        if not _MCP_AVAILABLE:
            print("[core] MCP 已跳过（mcp_client.client 未找到）")
        else:
            print("[core] MCP 已跳过（AGENT_ENABLE_MCP=false）")

    # ---------- 8. 工具集 ----------
    tools: list[Any] = []

    # L1: 本地文件
    tools += build_default_tools(str(cfg.project_path))

    # L2: 沙箱
    from tools import sandbox_ops as _sb
    tools += [_sb.__dict__[n] for n in SANDBOX_TOOLS]

    # L3: 事务
    from tools import transaction_ops as _tx
    tools += [_tx.__dict__[n] for n in TRANSACTION_TOOLS]

    # L4: Apply Patch
    tools.append(create_apply_patch_tool(str(cfg.project_path)))

    # L5: 代码库
    tools += [
        create_repo_map_tool(RepoMapBuilder(parser)),
        create_search_tool(bg_indexer),
        create_index_status_tool(bg_indexer),
        *create_dep_tools(dep_graph),
        *create_call_tools(call_graph),
        create_impact_tool(analyzer),
    ]

    # L6: 上下文
    from tools import context_ops as _ctx
    tools += [_ctx.__dict__[n] for n in CONTEXT_TOOLS]

    # L7: 测试
    from tools import test_ops as _test
    tools += [_test.__dict__[n] for n in TEST_TOOLS]

    # L8: 状态栏工具
    from tools import status_ops as _st
    tools += [_st.__dict__[n] for n in STATUS_TOOLS]

    # L9: 子 Agent 委派
    from tools import subagent_ops as _sub
    tools += [_sub.__dict__[n] for n in SUBAGENT_TOOLS]

    # L10: 技能
    tools.append(create_load_skill_tool(skill_registry))

    # L11: MCP
    tools += mcp_tools

    # L12: 工具搜索
    tools.append(create_tool_search_tool(tools))

    # 关键：按名字排序，保证工具定义块在所有请求中的顺序一致
    tools = sorted(tools, key=lambda t: t.name)

    # ---------- 9. 工具描述校验 ----------
    validate_tools(tools, strict=cfg.strict_lint)

    # ---------- 10. 系统提示 ----------
    system_prompt = load_system_prompt(cfg.agent_home)

    project_memory = load_project_memory(cfg.project_path)
    if project_memory:
        system_prompt = f"{system_prompt}\n\n## Project Memory\n{project_memory}"

    skill_meta = skill_registry.metadata_prompt()
    if skill_meta:
        system_prompt = f"{system_prompt}\n\n{skill_meta}"

    # ---------- 11. 上下文装配 ----------
    assembler = ContextAssembler(
        system_prompt=system_prompt,
        tool_definitions=render_tool_definitions(tools),
        project_memory="",
    )

    # ---------- 12. 轨迹持久化 ----------
    trajectory_writer = TrajectoryWriter(
        session_id=f"session-{id(cfg) & 0xffffff:x}",
        base_dir=str(cfg.trajectory_dir),
    )
    trajectory_mw = TrajectoryMiddleware(trajectory_writer)

    # ---------- 13. 中间件装配（缓存友好顺序）----------
    all_tool_names = [t.name for t in tools]
    skill_tool_map = {s.name: s.tools for s in skill_registry.all_skills()}

    circuit_breaker = CircuitBreakerMiddleware(
        CircuitBreakerConfig(
            max_repeats=3,
            max_consecutive_failures=3,
            max_retries_for_retryable=5,
        )
    )

    # ← 改动：创建共享的 metrics store
    from observability.metrics_store import MetricsStore
    from pathlib import Path as _Path

    metrics_db = _Path.home() / ".coding-agent" / "metrics.db"
    metrics_store = MetricsStore(str(metrics_db))

    # ← 改动：创建指标事件队列，MetricsMiddleware 往这里推事件，
    #         api/real.py 从队列取出并转成 SSE "metrics" 帧
    metrics_queue: "queue.Queue[dict]" = queue.Queue()

    def _on_metric(event: dict) -> None:
        """MetricsMiddleware 的回调，把指标事件塞进线程安全队列。"""
        try:
            metrics_queue.put_nowait(event)
        except Exception:
            pass

    middlewares = [
        # --- 会重写请求的中间件（先跑）---
        ContextCompactionMiddleware(
            model=llm,
            workspace=str(cfg.project_path),
            config=CompactionPipelineConfig(model_window=cfg.model_window),
        ),
        create_tool_filter_middleware(all_tool_names, skill_tool_map),

        # --- 指标采集（用共享 store + 事件回调）---
        MetricsMiddleware(
            store=metrics_store,
            model_name=cfg.model,
            debug=False,
            on_metric=_on_metric,          # ← 改动：传入回调
        ),

        # --- 工具层中间件（不改 messages/tools）---
        create_dependency_check_middleware(analyzer),
        circuit_breaker,

        # --- 只追加/只读的中间件 ---
        StatusBarMiddleware(status_bar),
        trajectory_mw,

        # --- 最后跑：缓存标记反映最终请求 ---
        create_prompt_cache_middleware(
            cache_ttl="5m",
            default_cache_key="coding-agent-v1",
        ),
    ]

    # ---------- 14. 组装 Agent ----------
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=InMemorySaver(),
    )

    # ---------- 15. 规划与修复图 ----------
    planning_graph = build_planning_graph(agent, InMemorySaver())

    def sandbox_exec(cmd: str):
        return sandbox.exec(cmd)

    repair_graph = build_repair_graph(agent, sandbox_exec, InMemorySaver())

    # ← 改动：结尾加日志
    log.info(
        "agent_build_done",
        tools=len(tools),
        skills=len(skill_registry.all_skills()),
        mcp_tools=len(mcp_tools),
    )

    # ---------- 16. 返回运行时 ----------
    return AgentRuntime(
        agent=agent,
        sandbox=sandbox,
        assembler=assembler,
        tools=tools,
        bg_indexer=bg_indexer,
        config=cfg,
        skill_registry=skill_registry,
        planning_graph=planning_graph,
        repair_graph=repair_graph,
        status_bar=status_bar,
        circuit_breaker=circuit_breaker,
        trajectory_writer=trajectory_writer,
        metrics_queue=metrics_queue,       # ← 改动：把队列交给运行时
    )