"""FastAPI 网关（含认证）。"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api.approval import approval_manager
from api.auth import (
    AUTH_MODE,
    OIDC_AUDIENCE,
    OIDC_ISSUER,
    REQUIRE_AUTH,
    User,
    get_current_user,
    require_admin,
    require_authenticated,
    require_writer,
)
from api.context_metrics import router as metrics_router
from api.files import router as files_router
from api.metrics_timeseries import router as timeseries_router
from api.mock import mock_chat_stream, sse
from api.schemas import (
    ApproveRequest,
    ApproveResponse,
    ApprovalListResponse,
    ApprovalRecord,
    AuthConfigResponse,
    ChatRequest,
    MetricsResponse,
    PendingApprovalListResponse,
    PendingApprovalModel,
    SessionInfo,
    UserInfo,
)


# ============================================================
# 全局状态
# ============================================================

AGENT_MODE = os.getenv("AGENT_MODE", "mock").lower()
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000",
).split(",")

_runtimes: dict[str, Any] = {}
_sessions: dict[str, dict] = {}          # session_id -> {user_id, created_at}
_runtime_lock = asyncio.Lock()


# ============================================================
# 生命周期
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[server] AGENT_MODE = {AGENT_MODE}")
    print(f"[server] AUTH_MODE = {AUTH_MODE}")
    print(f"[server] REQUIRE_AUTH = {REQUIRE_AUTH}")
    print(f"[server] CORS_ORIGINS = {CORS_ORIGINS}")

    if AGENT_MODE == "real":
        try:
            from agent.core import build_agent  # noqa: F401
            print("[server] real 模式：agent.core 可导入")
        except Exception as e:
            print(f"[server] ⚠️ real 模式导入失败，将降级为 mock: {e}")
            globals()["AGENT_MODE"] = "mock"

    # ← 新增：预初始化 metrics store
    try:
        from api.metrics_timeseries import get_store
        store = get_store()
        stats = store.stats()
        print(
            f"[server] Metrics store: {stats['db_path']} "
            f"({stats['total_rows']} rows)"
        )
    except Exception as e:
        print(f"[server] Metrics store 初始化失败: {e}")

    yield

    print("[server] 关闭中，清理 runtime...")
    for sid, rt in _runtimes.items():
        try:
            rt.close()
        except Exception as e:
            print(f"[server] 关闭 {sid} 失败: {e}")
    _runtimes.clear()
    _sessions.clear()


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
            # 校验归属
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
        oidc_redirect_uri=os.getenv("OIDC_REDIRECT_URI", "http://localhost:5173/auth/callback"),
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
async def health():
    return {
        "status": "ok",
        "mode": AGENT_MODE,
        "auth_mode": AUTH_MODE,
        "sessions": len(_sessions),
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
        result.append(SessionInfo(
            session_id=sid,
            index_ready=index_ready,
            prefix_stable=prefix_stable,
        ))
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
            print(f"[server] 关闭 {session_id} 失败: {e}")

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

    # 会话归属检查
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
            yield sse("error", {
                "source": "server",
                "message": f"{type(e).__name__}: {e}",
            })
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

    # 记录审批人
    print(f"[server] 审批: user={user.id}, approval={req.approval_id}, decision={req.decision}")
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
    return ApprovalListResponse(
        records=[ApprovalRecord(**r) for r in records]
    )


@app.get("/api/approvals/pending", response_model=PendingApprovalListResponse)
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
        port=8000,
        reload=True,
        log_level="info",
    )