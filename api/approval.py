"""审批管理器。

职责：
1. 维护每个会话的待审批请求队列
2. 记录审批历史
3. 与 SSE 流协同：流等待用户决策，另一路 HTTP 请求注入决策
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

# 敏感工具：需要审批才能执行
SENSITIVE_TOOLS = {
    "execute",
    "apply_patch",
    "write_file",
    "tx_commit",
    "tx_write",
    "git_push",
    "git_commit",
    "db_write",
}

# 永远不允许的命令模式（即使批准也拒绝）
FORBIDDEN_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    ":(){:|:&};:",
    "dd if=/dev/zero",
    "mkfs.",
    "> /dev/sda",
    "chmod -R 777 /",
]


@dataclass
class PendingApproval:
    """一条待审批记录。"""

    id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    args: dict
    reason: str
    thread_id: str
    checkpoint_id: str
    created_at: float = field(default_factory=time.time)
    decision_event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str | None = None
    edited_args: dict | None = None
    decided_by: str = "user"

    def resolve(
        self,
        decision: str,
        edited_args: dict | None = None,
        by: str = "user",
    ) -> None:
        """用户做出决策。"""
        self.decision = decision
        self.edited_args = edited_args
        self.decided_by = by
        self.decision_event.set()

    def to_model(self) -> dict:
        """转为 Pydantic 模型可用的 dict。"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "reason": self.reason,
            "thread_id": self.thread_id,
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
        }


class ApprovalManager:
    """审批管理器（进程级单例）。"""

    def __init__(self, timeout_seconds: float = 1800):
        self.timeout = timeout_seconds
        self._pending: dict[str, PendingApproval] = {}
        self._by_session: dict[str, list[str]] = {}
        self._history: list[dict] = []
        self._lock = asyncio.Lock()

    async def request(
        self,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        args: dict,
        thread_id: str,
        checkpoint_id: str,
        reason: str = "",
    ) -> PendingApproval:
        """创建一个待审批请求。危险模式自动拒绝。"""
        approval_id = f"appr-{uuid.uuid4().hex[:12]}"

        if self._is_forbidden(tool_name, args):
            approval = PendingApproval(
                id=approval_id,
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                reason=reason or "危险操作（系统自动拒绝）",
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
            )
            approval.resolve("reject", by="system")
            self._record_history(approval)
            return approval

        approval = PendingApproval(
            id=approval_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=args,
            reason=reason or self._default_reason(tool_name, args),
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
        )

        async with self._lock:
            self._pending[approval_id] = approval
            self._by_session.setdefault(session_id, []).append(approval_id)

        return approval

    async def resolve(
        self,
        approval_id: str,
        decision: str,
        edited_args: dict | None = None,
    ) -> bool:
        """用户做出决策。返回 True 表示成功，False 表示 approval_id 不存在。"""
        async with self._lock:
            approval = self._pending.get(approval_id)
            if approval is None:
                return False

        approval.resolve(decision, edited_args)
        self._record_history(approval)

        async with self._lock:
            self._pending.pop(approval_id, None)
            if approval_id in self._by_session.get(approval.session_id, []):
                self._by_session[approval.session_id].remove(approval_id)

        return True

    async def wait_decision(self, approval_id: str) -> PendingApproval:
        """等待用户决策（带超时）。超时自动拒绝。"""
        approval = self._pending.get(approval_id)
        if approval is None:
            raise KeyError(f"未知审批: {approval_id}")

        try:
            await asyncio.wait_for(
                approval.decision_event.wait(),
                timeout=self.timeout,
            )
        except TimeoutError:
            approval.resolve("reject", by="system")
            self._record_history(approval)
            async with self._lock:
                self._pending.pop(approval_id, None)
                if approval_id in self._by_session.get(approval.session_id, []):
                    self._by_session[approval.session_id].remove(approval_id)

        return approval

    async def list_pending(self, session_id: str) -> list[PendingApproval]:
        """列出某会话的待审批请求。"""
        async with self._lock:
            ids = self._by_session.get(session_id, [])
            return [self._pending[i] for i in ids if i in self._pending]

    async def list_history(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """列出审批历史（最新的在前）。"""
        async with self._lock:
            items = list(self._history)
        if session_id:
            items = [r for r in items if r["session_id"] == session_id]
        return list(reversed(items))[:limit]

    def _record_history(self, approval: PendingApproval) -> None:
        self._history.append(
            {
                "id": approval.id,
                "session_id": approval.session_id,
                "tool_call_id": approval.tool_call_id,
                "tool_name": approval.tool_name,
                "args": approval.args,
                "decision": approval.decision or "pending",
                "edited_args": approval.edited_args,
                "decided_at": time.time(),
                "decided_by": approval.decided_by,
            }
        )

    def _is_forbidden(self, tool_name: str, args: dict) -> bool:
        if tool_name != "execute":
            return False
        cmd = str(args.get("command", ""))
        return any(p in cmd for p in FORBIDDEN_PATTERNS)

    def _default_reason(self, tool_name: str, args: dict) -> str:
        if tool_name == "execute":
            cmd = args.get("command", "")
            return f"执行 shell 命令: {cmd[:80]}"
        if tool_name in ("write_file", "edit_file", "tx_edit"):
            return f"修改文件: {args.get('path', '?')}"
        if tool_name == "apply_patch":
            return "批量应用 patch"
        if tool_name == "tx_commit":
            return "提交事务修改"
        return f"调用敏感工具 {tool_name}"

    def is_sensitive(self, tool_name: str) -> bool:
        """判断工具是否需要审批。"""
        return tool_name in SENSITIVE_TOOLS


# 全局单例
approval_manager = ApprovalManager()
