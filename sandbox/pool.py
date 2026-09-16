"""沙箱工厂。

⚠️ 严重历史背景
=================

早期版本（我上一版给你的代码）做过容器池化，release 时执行过一个
"清空 /workspace 下所有文件"的命令。

意图是"清空容器工作区后归还池子"。

但 Docker 容器的 volume 挂载在 **容器启动时** 就固定了，运行期改
`sb.workspace` 只是改 Python 属性，容器内 /workspace 仍然指向首个任务
的项目目录。更糟的是，如果池里第一个任务挂载的是 A 项目，第二个任务
请求 B 项目时复用了同一个容器，release 时清理的其实是 A 项目——既
破坏了当前任务的隔离，又会误删别的项目。

结果：用户项目文件被删除。**这是我的设计错误，没有任何借口。**

本模块现在完全废弃池化：
- 不再缓存容器
- 不再跨任务复用
- 不再执行任何删除类命令
- release 只 stop 容器（移除容器对象，不碰挂载目录）

保留 SandboxPool 类名和相同的方法签名，是为了兼容 `agent/core.py`
已有的 import 和调用，无需改动调用方。

如果你未来确实要做池化，正确做法是：
1. 每个项目一个 pool（容器挂载固定目录，生命周期不超过项目）
2. 容器内区分 /workspace（只读或按需挂载）和 /sandbox（可写工作区）
3. release 只清理 /sandbox，绝不触碰 /workspace
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from sandbox.docker_backend import DockerSandbox


class SandboxPool:
    """沙箱工厂（类名保留为 SandboxPool 仅为兼容 import）。

    实际行为：
    - start()          : no-op
    - acquire(ws)      : 新建并启动一个 DockerSandbox
    - release(sb)      : 停止并移除容器（不做任何删除）
    - borrow(ws)       : 上下文管理器
    - shutdown()       : no-op
    """

    def __init__(
        self,
        image: str = "coding-agent-sandbox:latest",
        size: int = 3,
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
        network: bool = False,
        acquire_timeout: float = 15.0,
    ):
        self.image = image
        self.size = size
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network = network
        self.acquire_timeout = acquire_timeout

        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        """兼容方法。现在不做任何预热。"""
        with self._lock:
            self._started = True

    def shutdown(self) -> None:
        """兼容方法。没有池可以清理。"""
        with self._lock:
            self._started = False

    def acquire(self, workspace: str) -> DockerSandbox:
        """新建一个沙箱容器并启动。

        每次调用都返回全新的容器，绝不会复用旧容器。
        """
        sb = DockerSandbox(
            workspace=workspace,
            image=self.image,
            memory_limit=self.memory_limit,
            cpu_limit=self.cpu_limit,
            network=self.network,
        )
        sb.start()
        return sb

    def release(self, sb: DockerSandbox) -> None:
        """停止并移除容器。

        绝不执行任何删除类命令。
        挂载目录（宿主机上的 workspace）不会被触碰。
        """
        if sb is None:
            return
        try:
            sb.stop()
        except Exception:
            pass

    @contextmanager
    def borrow(self, workspace: str):
        sb = self.acquire(workspace)
        try:
            yield sb
        finally:
            self.release(sb)


# ============================================================
# 进程级单例
# ============================================================

_POOL_LOCK = threading.Lock()
_POOL: SandboxPool | None = None


def get_pool() -> SandboxPool:
    """返回进程级 SandboxPool 实例。

    注意：这个实例不做池化，只是提供统一的工厂接口。
    """
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = SandboxPool()
        return _POOL


__all__ = ["SandboxPool", "get_pool"]
