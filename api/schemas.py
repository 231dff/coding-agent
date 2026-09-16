"""API 请求/响应模型。

与 frontend/src/api/types.ts 严格对应，改动必须同步。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ============ 请求 ============

class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    thread_id: str = ""


class ApproveRequest(BaseModel):
    session_id: str
    approval_id: str
    decision: Literal["approve", "reject", "edit"]
    edited_args: dict[str, Any] | None = None


# ============ 响应 ============

class SessionInfo(BaseModel):
    session_id: str
    index_ready: bool
    prefix_stable: bool


class MetricsResponse(BaseModel):
    index: str
    prefix_stable: bool


class ApproveResponse(BaseModel):
    ok: bool
    decision: str


class ApprovalRecord(BaseModel):
    id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    decision: str
    edited_args: dict[str, Any] | None = None
    decided_at: float
    decided_by: str = "user"


class ApprovalListResponse(BaseModel):
    records: list[ApprovalRecord]


class PendingApprovalModel(BaseModel):
    id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    reason: str
    thread_id: str
    checkpoint_id: str
    created_at: float


class PendingApprovalListResponse(BaseModel):
    pending: list[PendingApprovalModel]


# ============ SSE 事件 ============

class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    content: str
    session_id: str


class ToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    timestamp: float


class ToolEndEvent(BaseModel):
    type: Literal["tool_end"] = "tool_end"
    tool_call_id: str
    tool_name: str
    output: str
    timestamp: float


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    source: Literal["server", "tool"]
    message: str
    tool_name: str | None = None


class ApprovalRequiredEvent(BaseModel):
    type: Literal["approval_required"] = "approval_required"
    session_id: str
    approval_id: str
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    reason: str
    thread_id: str
    checkpoint_id: str
    timestamp: float


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    session_id: str

# ============ 认证 ============

class UserInfo(BaseModel):
    id: str
    name: str
    email: str = ""
    roles: list[str] = []
    picture: str = ""


class AuthConfigResponse(BaseModel):
    """前端初始化需要的认证配置。"""
    mode: str                          # mock | oidc | disabled
    require_auth: bool
    oidc_authority: str = ""
    oidc_client_id: str = ""
    oidc_redirect_uri: str = ""
    oidc_scope: str = "openid profile email"