"""Day 12: 持久化 shell session。

在同一容器内保持 cwd 和 shell 变量的连续性，
避免每次命令都从 /workspace 开始。

修复记录（2026-10-06）：
  - 旧逻辑：command.startswith("cd ") 就认为整条命令是 cd，
    导致 `cd /tmp && python xxx.py` 被误判，把整串当作 cwd 污染 session。
  - 新逻辑：用 shlex.split 严格判定「纯 cd <path>」：
      * token 数恰好 2
      * 第二 token 不含 shell 元字符（|&;<>()$`\"'*?[]{}）
    `cd /tmp && xxx` 会分词为 3+ 个 token，不匹配 → 走正常执行路径。
"""

from __future__ import annotations

import shlex
import uuid
from dataclasses import dataclass, field

from sandbox.base import ExecResult, Sandbox

# shell 元字符：出现任一即视为「复合命令」，不做状态拦截
_SHELL_META = set("|&;<>()$`\\\"'*?[]{}")


def _has_shell_meta(s: str) -> bool:
    return any(c in _SHELL_META for c in s)


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

        特殊处理（严格匹配）：
        - 只有「纯粹的」`cd <path>` 才更新 session.cwd
        - 只有「纯粹的」`export KEY=VALUE` 才更新 session.env
        - 其他一律作为普通命令交给沙箱执行
        """
        session = self.sessions.get(session_id) if session_id else self.default_session
        if session is None:
            raise KeyError(f"未知 session: {session_id}")

        # ★ 防御：如果 session.cwd 已被污染（含空格或元字符），重置
        if _has_shell_meta(session.cwd):
            session.cwd = "/workspace"

        stripped = command.strip()
        tokens = self._safe_split(stripped)

        # ---------- 严格拦截：纯 cd ----------
        if (
            len(tokens) == 2
            and tokens[0] == "cd"
            and not _has_shell_meta(tokens[1])
        ):
            resolved = self._resolve_cwd(session.cwd, tokens[1])
            session.cwd = resolved
            session.history.append(command)
            return ExecResult(
                exit_code=0,
                stdout=f"cwd 切换到 {resolved}",
                stderr="",
                duration_s=0.0,
            )

        # ---------- 严格拦截：纯 export ----------
        if (
            len(tokens) == 2
            and tokens[0] == "export"
            and "=" in tokens[1]
            and not _has_shell_meta(tokens[1])
        ):
            k, v = tokens[1].split("=", 1)
            session.env[k.strip()] = v.strip().strip("'\"")
            session.history.append(command)
            return ExecResult(
                exit_code=0,
                stdout=f"已设置 {k.strip()}={v.strip()}",
                stderr="",
                duration_s=0.0,
            )

        # ---------- 正常执行 ----------
        result = self.sandbox.exec(
            command,
            timeout=timeout,
            cwd=session.cwd,
            env=session.env,
        )
        session.history.append(command)
        return result

    @staticmethod
    def _safe_split(cmd: str) -> list[str]:
        """shlex 分词；失败时返回空列表（保守：不识别为状态更新）。"""
        try:
            return shlex.split(cmd)
        except ValueError:
            return []

    @staticmethod
    def _resolve_cwd(current: str, target: str) -> str:
        """解析 cd 目标路径（不实际验证存在性，由下次命令报错）。"""
        import posixpath

        # ★ 双保险：拒绝含元字符的目标
        if _has_shell_meta(target):
            return current

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
