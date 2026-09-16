"""文件访问 API。

提供目录树和文件内容两个端点，供前端文件浏览器使用。
所有端点需要认证。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from agent.config import AgentConfig
from api.auth import User, require_authenticated


router = APIRouter(prefix="/api/files", tags=["files"])


# ============================================================
# 配置
# ============================================================

# 忽略的目录
IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".egg-info",
    ".idea",
    ".vscode",
    ".code_index",
    ".context_offload",
    ".agent_memory",
    ".sandbox_outputs",
    "node_modules",
}

# 忽略的文件/目录前缀
IGNORE_PREFIXES = (".tx_", ".DS_Store")

# 单文件最大读取字节数
MAX_CONTENT_BYTES = 500_000


# ============================================================
# 辅助函数
# ============================================================

def _get_workspace() -> Path:
    """获取工作区路径。"""
    cfg = AgentConfig()
    return Path(cfg.workspace).resolve()


def _safe_resolve(root: Path, rel: str) -> Path:
    """把相对路径解析到 root 下，防止目录穿越。

    攻击示例：path="../../etc/passwd"
    这里会抛 403。
    """
    # 移除开头的 / 或 \
    rel = rel.lstrip("/\\")
    # 处理空路径
    if not rel:
        return root

    p = (root / rel).resolve()

    # 确保解析后仍在 root 内
    try:
        p.relative_to(root)
    except ValueError:
        raise HTTPException(403, f"路径越界: {rel}")

    return p


def _should_ignore(name: str) -> bool:
    """判断目录/文件是否应被忽略。"""
    if name in IGNORE_DIRS:
        return True
    for prefix in IGNORE_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _relative(root: Path, target: Path) -> str:
    """把绝对路径转为相对于 root 的路径，使用 / 分隔。"""
    if target == root:
        return "."
    return str(target.relative_to(root)).replace("\\", "/")


# ============================================================
# 路由
# ============================================================

@router.get("/tree")
async def get_tree(
    path: str = Query(".", description="相对路径"),
    user: User = Depends(require_authenticated),
):
    """列出目录下的直接子项（不递归）。

    前端点击目录时按需请求下一层，避免大项目一次性加载。

    Args:
        path: 相对于工作区根目录的路径，默认 "."。
    """
    root = _get_workspace()
    target = _safe_resolve(root, path)

    if not target.exists():
        raise HTTPException(404, f"路径不存在: {path}")
    if not target.is_dir():
        raise HTTPException(400, f"不是目录: {path}")

    entries = []
    try:
        # 目录在前，文件在后；同类按名称排序
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if _should_ignore(item.name):
                continue

            rel = _relative(root, item)
            entry: dict = {
                "name": item.name,
                "path": rel,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    entry["size"] = 0
            entries.append(entry)
    except PermissionError as e:
        raise HTTPException(403, f"无权限访问: {e}")
    except OSError as e:
        raise HTTPException(500, f"读取目录失败: {e}")

    return {
        "path": _relative(root, target),
        "entries": entries,
    }


@router.get("/content")
async def get_content(
    path: str = Query(..., description="相对路径"),
    user: User = Depends(require_authenticated),
):
    """读取文件内容。

    Args:
        path: 相对于工作区根目录的路径，必填。
    """
    root = _get_workspace()
    target = _safe_resolve(root, path)

    if not target.exists():
        raise HTTPException(404, f"文件不存在: {path}")
    if not target.is_file():
        raise HTTPException(400, f"不是文件: {path}")

    try:
        size = target.stat().st_size
    except OSError as e:
        raise HTTPException(500, f"读取文件信息失败: {e}")

    if size > MAX_CONTENT_BYTES:
        raise HTTPException(
            413,
            f"文件过大 ({size} bytes)，超过 {MAX_CONTENT_BYTES} 字节限制",
        )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError as e:
        raise HTTPException(403, f"无权限读取: {e}")
    except Exception as e:
        raise HTTPException(500, f"读取失败: {e}")

    return {
        "path": _relative(root, target),
        "content": content,
        "size": size,
    }


@router.get("/stat")
async def get_stat(
    path: str = Query(..., description="相对路径"),
    user: User = Depends(require_authenticated),
):
    """查询文件/目录的元数据（不读取内容）。

    用途：文件浏览时判断是否需要预取内容。

    Args:
        path: 相对于工作区根目录的路径。
    """
    root = _get_workspace()
    target = _safe_resolve(root, path)

    if not target.exists():
        raise HTTPException(404, f"路径不存在: {path}")

    try:
        st = target.stat()
    except OSError as e:
        raise HTTPException(500, f"读取元数据失败: {e}")

    return {
        "path": _relative(root, target),
        "type": "dir" if target.is_dir() else "file",
        "size": st.st_size,
        "mtime": st.st_mtime,
        "readable": os.access(target, os.R_OK),
    }