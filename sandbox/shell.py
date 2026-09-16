"""Day 12: 持久化 shell session。

在同一容器内保持 cwd 和 shell 变量的连续性，
避免每次命令都从 /workspace 开始。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sandbox.base import ExecResult, Sandbox


@dataclass
class ShellSession:
    """一个持久化的 shell 上下文。

    通过保存 cwd 和环境变量，在每次 exec 前重放，
    实现跨调用的状态保持。
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    cwd: str = "/workspace"
    env: dict[str, str] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)


class ShellManager:
    """管理一个沙箱内的多个 shell session。"""

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self.sessions: dict[str, ShellSession] = {}
        self.default_session = self._new_session()

    def _new_session(self) -> ShellSession:
        s = ShellSession()
        self.sessions[s.session_id] = s
        return s

    def execute(
        self,
        command: str,
        timeout: int = 60,
        session_id: str | None = None,
    ) -> ExecResult:
        """在指定 session 中执行命令。

        特殊处理：
        - `cd <path>` 命令不实际执行，只更新 session 的 cwd
        - `export X=Y` 命令更新 session 的环境变量
        """
        session = self.sessions.get(session_id) if session_id else self.default_session
        if session is None:
            raise KeyError(f"未知 session: {session_id}")

        # 拦截 cd 命令
        cmd_stripped = command.strip()
        if cmd_stripped.startswith("cd "):
            target = cmd_stripped[3:].strip()
            # 解析相对/绝对路径
            resolved = self._resolve_cwd(session.cwd, target)
            session.cwd = resolved
            session.history.append(command)
            return ExecResult(
                exit_code=0,
                stdout=f"cwd 切换到 {resolved}",
                stderr="",
                duration_s=0.0,
            )

        # 拦截 export 命令
        if cmd_stripped.startswith("export "):
            assignment = cmd_stripped[7:].strip()
            if "=" in assignment:
                k, v = assignment.split("=", 1)
                session.env[k.strip()] = v.strip().strip("'\"")
                session.history.append(command)
                return ExecResult(
                    exit_code=0,
                    stdout=f"已设置 {k.strip()}={v.strip()}",
                    stderr="",
                    duration_s=0.0,
                )

        # 实际执行
        result = self.sandbox.exec(
            command,
            timeout=timeout,
            cwd=session.cwd,
            env=session.env,
        )
        session.history.append(command)
        return result

    @staticmethod
    def _resolve_cwd(current: str, target: str) -> str:
        """解析 cd 目标路径（不实际验证存在性，由下次命令报错）。"""
        import posixpath

        if target.startswith("/"):
            return posixpath.normpath(target)
        return posixpath.normpath(posixpath.join(current, target))

    def reset(self, session_id: str | None = None) -> None:
        """重置 session 的 cwd 和环境变量。"""
        if session_id:
            s = self.sessions.get(session_id)
            if s:
                s.cwd = "/workspace"
                s.env.clear()
                s.history.clear()
        else:
            self.default_session = self._new_session()
