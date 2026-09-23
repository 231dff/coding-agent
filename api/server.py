"""FastAPI 网关（含认证、健康检查、优雅关闭）。"""

from __future__ import annotations

import asyncio
import os
import signal
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from api.approval import approval_manager
from api.auth import (
    AUTH_MODE,
    OIDC_ISSUER,
    REQUIRE_AUTH,
    User,
    require_admin,
    require_authenticated,
    require_writer,
)
from api.context_metrics import router as metrics_router
from api.files import router as files_router
from api.metrics_timeseries import router as timeseries_router
from api.mock import mock_chat_stream, sse
from api.schemas import (
    ApprovalListResponse,
    ApprovalRecord,
    ApproveRequest,
    ApproveResponse,
    AuthConfigResponse,
    ChatRequest,
    MetricsResponse,
    PendingApprovalListResponse,
    PendingApprovalModel,
    SessionInfo,
    UserInfo,
)
from observability.logger import configure_logging, get_logger
from observability.trace import (
    get_trace_id,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
)

# 确保日志系统已初始化（幂等，重复调用无副作用）
configure_logging()
log = get_logger("server")


# ============================================================
# 全局状态
# ============================================================

AGENT_MODE = os.getenv("AGENT_MODE", "mock").lower()
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")

_runtimes: dict[str, Any] = {}
_sessions: dict[str, dict] = {}  # session_id -> {user_id, created_at}
_runtime_lock = asyncio.Lock()


# ============================================================
# 生命周期：初始化 + 优雅关闭
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "server_config",
        agent_mode=AGENT_MODE,
        auth_mode=AUTH_MODE,
        require_auth=REQUIRE_AUTH,
        cors_origins=CORS_ORIGINS,
    )

    if AGENT_MODE == "real":
        try:
            from agent.core import build_agent  # noqa: F401

            log.info("server_mode", mode="real", note="agent.core 可导入")
        except Exception as e:
            log.warning("server_real_mode_failed", error=str(e), fallback="mock")
            globals()["AGENT_MODE"] = "mock"

    # 预初始化 metrics store
    try:
        from api.metrics_timeseries import get_store

        store = get_store()
        stats = store.stats()
        log.info(
            "metrics_store_ready",
            db_path=stats["db_path"],
            rows=stats["total_rows"],
        )
    except Exception as e:
        log.warning("metrics_store_init_failed", error=str(e))

    # ★ 优雅关闭：捕获 SIGTERM / SIGINT
    shutdown_event = asyncio.Event()

    def _on_shutdown_signal():
        log.info("shutdown_signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_shutdown_signal)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    yield

    # 等待正在处理的请求（最多 10 秒）
    log.info("shutdown_waiting", max_wait_s=10)
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    # 清理所有 runtime
    log.info("shutdown_cleanup_runtime")
    for sid, rt in list(_runtimes.items()):
        if rt is None:
            continue
        try:
            rt.close()
        except Exception as e:
            log.warning("shutdown_session_failed", session_id=sid, error=str(e))

    _runtimes.clear()
    _sessions.clear()
    log.info("shutdown_complete")


# ============================================================
# 应用
# ============================================================

app = FastAPI(
    title="Coding Agent API",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ★ Trace ID 中间件
# ============================================================


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """为每个请求生成 trace_id，并写入响应头。"""
    tid = request.headers.get("X-Trace-Id", "")
    if tid:
        set_trace_id(tid)
    else:
        tid = new_trace_id()

    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response
    finally:
        reset_trace_id()


app.include_router(files_router)
app.include_router(metrics_router)
app.include_router(timeseries_router)


# ============================================================
# 辅助
# ============================================================


async def _get_or_create_runtime(session_id: str, user_id: str):
    """获取或创建 AgentRuntime。"""
    async with _runtime_lock:
        if session_id in _runtimes:
            meta = _sessions.get(session_id)
            if meta and meta["user_id"] != user_id:
                raise HTTPException(403, "无权访问该会话")
            return _runtimes[session_id]

        from agent.config import AgentConfig
        from agent.core import build_agent

        cfg = AgentConfig()
        rt = build_agent(cfg)
        _runtimes[session_id] = rt
        _sessions[session_id] = {
            "user_id": user_id,
            "created_at": asyncio.get_event_loop().time(),
        }
        return rt


def _check_session_owner(session_id: str, user: User) -> None:
    """校验会话归属。admin 可访问全部。"""
    if user.is_admin():
        return
    meta = _sessions.get(session_id)
    if meta and meta["user_id"] != user.id:
        raise HTTPException(403, "无权访问该会话")


def _detect_scenario(message: str) -> str:
    msg = message.lower()
    if "/approval" in msg or "审批" in msg:
        return "approval"
    if "/slow" in msg or "慢速" in msg:
        return "slow"
    if "/error" in msg or "报错" in msg:
        return "error"
    if "/multi" in msg or "多工具" in msg:
        return "multi_tool"
    if "/code" in msg or "代码" in msg:
        return "code"
    return "default"


# ============================================================
# ★ 健康检查与指标
# ============================================================


@app.get("/health")
async def health():
    """存活探针。"""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """就绪探针：检查关键依赖。"""
    checks: dict[str, str] = {}

    # Memory store
    try:
        from memory.store import get_store

        get_store()
        checks["memory"] = "ok"
    except Exception as e:
        checks["memory"] = f"fail: {type(e).__name__}"

    # Docker（可选，不阻断）
    try:
        import docker

        docker.from_env().ping()
        checks["docker"] = "ok"
    except Exception:
        checks["docker"] = "unavailable"

    # LLM 配置（只看 key 是否存在，不调用）
    checks["llm"] = (
        "configured" if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") else "missing"
    )

    hard_ok = checks.get("memory") == "ok" and checks.get("llm") == "configured"

    return JSONResponse(
        checks,
        status_code=200 if hard_ok else 503,
    )


@app.get("/metrics")
async def metrics():
    """Prometheus 格式的简单指标。"""
    from pathlib import Path

    lines: list[str] = []

    # 指标库统计
    try:
        from observability.metrics_store import MetricsStore

        store = MetricsStore(str(Path.home() / ".coding-agent" / "metrics.db"))
        stats = store.stats()

        lines.append("# HELP agent_metrics_rows_total Total metric rows")
        lines.append("# TYPE agent_metrics_rows_total counter")
        lines.append(f"agent_metrics_rows_total {stats.get('total_rows', 0)}")

        lines.append("# HELP agent_metrics_db_bytes DB file size")
        lines.append("# TYPE agent_metrics_db_bytes gauge")
        lines.append(f"agent_metrics_db_bytes {stats.get('db_size_bytes', 0)}")
    except Exception:
        pass

    # 会话数
    lines.append("# HELP agent_sessions_active Active sessions")
    lines.append("# TYPE agent_sessions_active gauge")
    lines.append(f"agent_sessions_active {len(_sessions)}")

    return Response(
        "\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )


# ============================================================
# 认证路由
# ============================================================


@app.get("/api/auth/config", response_model=AuthConfigResponse)
async def get_auth_config():
    """返回前端初始化所需的认证配置（无需认证即可访问）。"""
    return AuthConfigResponse(
        mode=AUTH_MODE,
        require_auth=REQUIRE_AUTH,
        oidc_authority=OIDC_ISSUER if AUTH_MODE == "oidc" else "",
        oidc_client_id=os.getenv("OIDC_CLIENT_ID", ""),
        oidc_redirect_uri=os.getenv(
            "OIDC_REDIRECT_URI",
            "http://localhost:5173/auth/callback",
        ),
        oidc_scope=os.getenv("OIDC_SCOPE", "openid profile email"),
    )


@app.get("/api/auth/me", response_model=UserInfo)
async def get_me(user: User = Depends(require_authenticated)):
    """返回当前用户信息。"""
    return UserInfo(**user.to_dict())


# ============================================================
# 基础路由
# ============================================================


@app.get("/api/health")
async def api_health():
    """兼容旧路径。"""
    return {
        "status": "ok",
        "mode": AGENT_MODE,
        "auth_mode": AUTH_MODE,
        "sessions": len(_sessions),
        "trace_id": get_trace_id(),
    }


@app.get("/api/sessions", response_model=list[SessionInfo])
async def list_sessions(user: User = Depends(require_authenticated)):
    """列出当前用户可见的会话。admin 看到全部。"""
    result: list[SessionInfo] = []
    for sid, rt in _runtimes.items():
        meta = _sessions.get(sid)
        if not user.is_admin() and meta and meta["user_id"] != user.id:
            continue

        try:
            index_ready = rt.index_ready()
            prefix_stable = rt.check_prefix_stability()
        except Exception:
            index_ready = False
            prefix_stable = False
        result.append(
            SessionInfo(
                session_id=sid,
                index_ready=index_ready,
                prefix_stable=prefix_stable,
            )
        )
    return result


@app.delete("/api/sessions/{session_id}")
async def close_session(
    session_id: str,
    user: User = Depends(require_writer),
):
    _check_session_owner(session_id, user)

    async with _runtime_lock:
        rt = _runtimes.pop(session_id, None)
        _sessions.pop(session_id, None)

    if rt is not None:
        try:
            rt.close()
        except Exception as e:
            log.warning("session_close_failed", session_id=session_id, error=str(e))

    return {"ok": True}


@app.get("/api/metrics", response_model=MetricsResponse)
async def get_metrics(
    session_id: str = Query(...),
    user: User = Depends(require_authenticated),
):
    _check_session_owner(session_id, user)

    rt = _runtimes.get(session_id)
    if rt is None:
        return MetricsResponse(index="(无索引)", prefix_stable=True)

    try:
        index_text = rt.bg_indexer.snapshot().to_text()
        prefix_stable = rt.check_prefix_stability()
    except Exception:
        index_text = "(不可用)"
        prefix_stable = False

    return MetricsResponse(index=index_text, prefix_stable=prefix_stable)


# ============================================================
# 对话路由
# ============================================================


@app.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: User = Depends(require_writer),
):
    """流式对话端点（SSE）。"""
    session_id = req.session_id or uuid.uuid4().hex[:12]
    thread_id = req.thread_id or session_id

    _check_session_owner(session_id, user)

    async def event_generator():
        try:
            if AGENT_MODE == "mock":
                scenario = _detect_scenario(req.message)
                async for chunk in mock_chat_stream(req.message, session_id, scenario):
                    if await request.is_disconnected():
                        break
                    yield chunk
            else:
                rt = await _get_or_create_runtime(session_id, user.id)
                from api.real import real_chat_stream

                async for chunk in real_chat_stream(rt, req.message, session_id, thread_id):
                    if await request.is_disconnected():
                        break
                    yield chunk
        except Exception as e:
            yield sse(
                "error",
                {
                    "source": "server",
                    "message": f"{type(e).__name__}: {e}",
                },
            )
            yield sse("done", {"session_id": session_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/chat/approve", response_model=ApproveResponse)
async def approve_tool(
    req: ApproveRequest,
    user: User = Depends(require_writer),
):
    """人工审批工具调用。"""
    _check_session_owner(req.session_id, user)

    ok = await approval_manager.resolve(
        req.approval_id,
        req.decision,
        req.edited_args,
    )
    if not ok:
        raise HTTPException(404, f"未知审批: {req.approval_id}")

    log.info(
        "approval_decision",
        user_id=user.id,
        approval_id=req.approval_id,
        decision=req.decision,
    )
    return ApproveResponse(ok=True, decision=req.decision)


@app.get("/api/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    session_id: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_authenticated),
):
    """列出审批历史。普通用户只能看自己的会话。"""
    if session_id:
        _check_session_owner(session_id, user)

    records = await approval_manager.list_history(session_id or None, limit=limit)
    return ApprovalListResponse(records=[ApprovalRecord(**r) for r in records])


@app.get(
    "/api/approvals/pending",
    response_model=PendingApprovalListResponse,
)
async def list_pending_approvals(
    session_id: str = Query(...),
    user: User = Depends(require_authenticated),
):
    _check_session_owner(session_id, user)

    pending = await approval_manager.list_pending(session_id)
    return PendingApprovalListResponse(
        pending=[PendingApprovalModel(**p.to_model()) for p in pending]
    )


# ============================================================
# 管理员路由
# ============================================================


@app.get("/api/admin/sessions")
async def admin_list_all_sessions(user: User = Depends(require_admin)):
    """管理员查看所有会话。"""
    return [
        {
            "session_id": sid,
            "user_id": _sessions.get(sid, {}).get("user_id", "unknown"),
            "created_at": _sessions.get(sid, {}).get("created_at", 0),
        }
        for sid in _runtimes.keys()
    ]


@app.get("/api/admin/users")
async def admin_list_users(user: User = Depends(require_admin)):
    """管理员查看 mock 用户列表（仅 mock 模式）。"""
    if AUTH_MODE != "mock":
        raise HTTPException(400, "仅 mock 模式支持")
    from api.auth import MOCK_USERS

    return [u.to_dict() for u in MOCK_USERS.values()]


# ============================================================
# 调试入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
        log_level="info",
        timeout_graceful_shutdown=10,  # ★ 优雅关闭超时
    )
