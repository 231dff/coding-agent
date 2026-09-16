"""认证与授权。

支持两种模式：
- mock: 开发用，从固定 token 解析出预设用户
- oidc: 生产用，验证 JWT 签名并提取声明

角色：
- admin: 全部权限，可管理用户、查看所有会话
- developer: 可发消息、审批工具、编辑文件
- viewer: 只读，不能发消息、不能审批
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv()

Role = Literal["admin", "developer", "viewer"]


@dataclass
class User:
    """当前用户。"""

    id: str
    name: str
    email: str = ""
    roles: list[Role] = field(default_factory=lambda: ["developer"])
    picture: str = ""

    @property
    def primary_role(self) -> Role:
        """返回最高优先级的角色。"""
        for r in ("admin", "developer", "viewer"):
            if r in self.roles:
                return r  # type: ignore
        return "viewer"

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def is_admin(self) -> bool:
        return self.has_role("admin")

    def can_write(self) -> bool:
        """是否可执行写操作（发消息、审批）。"""
        return self.primary_role in ("admin", "developer")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "roles": self.roles,
            "picture": self.picture,
        }


# ============================================================
# 配置
# ============================================================

AUTH_MODE = os.getenv("AUTH_MODE", "mock").lower()  # mock | oidc | disabled
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "")
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "")

# 是否强制认证。生产必须为 true，开发可以为 false
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() == "true"

# ← 新增：mock 模式下，无 token 时使用的默认用户角色
# 开发时改成 "developer" 或 "admin" 可跳过登录直接使用
MOCK_DEFAULT_USER_KEY = os.getenv("MOCK_DEFAULT_USER", "mock-dev-token")


# ============================================================
# Mock 用户（开发用）
# ============================================================

MOCK_USERS: dict[str, User] = {
    "mock-admin-token": User(
        id="u-admin",
        name="Admin User",
        email="admin@example.com",
        roles=["admin"],
    ),
    "mock-dev-token": User(
        id="u-dev",
        name="Developer",
        email="dev@example.com",
        roles=["developer"],
    ),
    "mock-viewer-token": User(
        id="u-viewer",
        name="Viewer",
        email="viewer@example.com",
        roles=["viewer"],
    ),
}


# ============================================================
# JWT 验证（OIDC 模式）
# ============================================================

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL = 3600  # 缓存 1 小时


def _fetch_jwks() -> dict:
    """从 OIDC provider 拉取 JWKS。"""
    import httpx

    now = time.time()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["fetched_at"] < _JWKS_TTL:
        return _jwks_cache["keys"]

    if not OIDC_JWKS_URL:
        raise RuntimeError("OIDC_JWKS_URL 未配置")

    resp = httpx.get(OIDC_JWKS_URL, timeout=10)
    resp.raise_for_status()
    keys = resp.json()

    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


def _verify_jwt_oidc(token: str) -> dict:
    """验证 OIDC JWT，返回 payload。"""
    import jwt
    from jwt import PyJWKClient

    if not OIDC_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC 未配置",
        )

    try:
        jwks_client = PyJWKClient(OIDC_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=OIDC_AUDIENCE or None,
            issuer=OIDC_ISSUER or None,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效: {e}",
        )


def _payload_to_user(payload: dict) -> User:
    """从 JWT payload 提取用户信息。"""
    user_id = payload.get("sub") or payload.get("user_id") or payload.get("oid") or "unknown"
    name = (
        payload.get("name")
        or payload.get("preferred_username")
        or payload.get("nickname")
        or user_id
    )
    email = payload.get("email", "")
    picture = payload.get("picture", "")

    raw_roles: list[str] = []
    if "realm_access" in payload and isinstance(payload["realm_access"], dict):
        raw_roles.extend(payload["realm_access"].get("roles", []))
    if "roles" in payload and isinstance(payload["roles"], list):
        raw_roles.extend(payload["roles"])
    if "groups" in payload and isinstance(payload["groups"], list):
        raw_roles.extend(payload["groups"])

    roles: list[Role] = []
    for r in raw_roles:
        if r in ("admin", "developer", "viewer"):
            roles.append(r)  # type: ignore

    if not roles:
        roles = ["viewer"]

    return User(
        id=user_id,
        name=name,
        email=email,
        roles=roles,
        picture=picture,
    )


# ============================================================
# 认证依赖
# ============================================================

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """从 Authorization header 解析当前用户。

    行为取决于 AUTH_MODE 和 REQUIRE_AUTH：
    - disabled: 返回匿名 admin（开发便利）
    - mock + 无 token: 返回默认 mock 用户（开发便利）           # ← 新增分支
    - mock + 有 token: 从 MOCK_USERS 查
    - oidc: 验证 JWT
    """
    if AUTH_MODE == "disabled":
        # 完全关闭认证
        return User(
            id="anonymous",
            name="Anonymous",
            roles=["admin"],
        )

    # ← 新增：mock 模式，无 token 时返回默认用户（跳过登录直接开发）
    if AUTH_MODE == "mock" and creds is None:
        default_user = MOCK_USERS.get(MOCK_DEFAULT_USER_KEY)
        if default_user is not None:
            return default_user
        # 兜底：如果配置的 key 不存在，返回 Developer
        return User(
            id="u-dev",
            name="Developer",
            email="dev@example.com",
            roles=["developer"],
        )

    if not REQUIRE_AUTH and creds is None:
        # 允许匿名访问，给最小权限
        return User(
            id="anonymous",
            name="Anonymous",
            roles=["viewer"],
        )

    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = creds.credentials

    if AUTH_MODE == "mock":
        user = MOCK_USERS.get(token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"未知 mock token。可用 token: {list(MOCK_USERS.keys())}",
            )
        return user

    if AUTH_MODE == "oidc":
        payload = _verify_jwt_oidc(token)
        return _payload_to_user(payload)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"未知认证模式: {AUTH_MODE}",
    )


async def require_authenticated(
    user: User = Depends(get_current_user),
) -> User:
    """要求已认证。"""
    if user.id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录",
        )
    return user


async def require_writer(
    user: User = Depends(get_current_user),
) -> User:
    """要求写权限（admin 或 developer）。"""
    if not user.can_write():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前角色 {user.primary_role} 无写权限",
        )
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """要求管理员权限。"""
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
