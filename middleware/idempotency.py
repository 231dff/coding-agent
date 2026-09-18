"""工具幂等性中间件。

对"写"类工具，检测是否重复调用相同参数。
同参数、同会话内，第二次调用直接返回缓存结果。

作用：
- 防止因重试导致的重复写操作
- 减少不必要的工具调用
- 对只读工具有微弱的缓存收益

设计：
- 只对"写"类工具生效（避免误缓存只读结果）
- Key = tool_name + 参数哈希
- 同会话内有效（不持久化，进程结束即清）
- 命中缓存时返回首次结果

不适用于：
- 有副作用的工具（如打电话、发邮件）—— 这些工具本身就是幂等的反例
- 结果不确定的工具（如 get_current_time）—— 但这类一般不写入
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware

# ============================================================
# 需要幂等性保护的写类工具
# ============================================================

_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        # 文件写
        "write_file",
        "edit_file",
        "apply_patch",
        # 事务
        "begin_transaction",
        "tx_edit",
        "tx_commit",
        "tx_rollback",
        # 沙箱内写
        "sandbox_write",
        # 测试（跑测试有副作用：可能修改临时文件、数据库等）
        "run_tests",
        # MCP 写类工具（保守起见）
        "git_add",
        "git_commit",
        "git_push",
    }
)


# ============================================================
# IdempotencyMiddleware
# ============================================================


class IdempotencyMiddleware(AgentMiddleware):
    """工具幂等性中间件。

    缓存策略：
    - 只对 _WRITE_TOOLS 里的工具生效
    - Key = tool_name + 参数哈希
    - 同会话内有效
    - 命中缓存时直接返回首次结果

    配置：
    - AGENT_IDEMPOTENCY=true（默认）：启用
    - AGENT_IDEMPOTENCY=false：禁用
    """

    name: str = "IdempotencyMiddleware"

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled
        self._cache: dict[str, Any] = {}

    # ---------- 同步 ----------

    def wrap_tool_call(self, request, handler):
        if not self.enabled:
            return handler(request)

        tool_call = self._extract_tool_call(request)
        if tool_call is None:
            return handler(request)

        tool_name = tool_call.get("name", "")
        if tool_name not in _WRITE_TOOLS:
            return handler(request)

        args = tool_call.get("args", {})
        cache_key = self._make_key(tool_name, args)

        # 命中缓存 → 直接返回首次结果
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 首次执行
        result = handler(request)
        self._cache[cache_key] = result
        return result

    # ---------- 异步 ----------

    async def awrap_tool_call(self, request, handler):
        if not self.enabled:
            return await handler(request)

        tool_call = self._extract_tool_call(request)
        if tool_call is None:
            return await handler(request)

        tool_name = tool_call.get("name", "")
        if tool_name not in _WRITE_TOOLS:
            return await handler(request)

        args = tool_call.get("args", {})
        cache_key = self._make_key(tool_name, args)

        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await handler(request)
        self._cache[cache_key] = result
        return result

    # ---------- 内部 ----------

    @staticmethod
    def _extract_tool_call(request) -> dict | None:
        """从 request 里取 tool_call。

        兼容 dict 和 object 两种形式。
        """
        tool_call = getattr(request, "tool_call", None)
        if tool_call is None and hasattr(request, "get"):
            tool_call = request.get("tool_call")
        return tool_call

    @staticmethod
    def _make_key(tool_name: str, args: dict) -> str:
        """生成缓存 key。

        - 用 sort_keys 保证参数顺序稳定
        - 用 MD5 缩短长度
        - 前缀带 tool_name 便于调试
        """
        try:
            args_str = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            args_str = str(args)

        digest = hashlib.md5(args_str.encode("utf-8")).hexdigest()[:12]
        return f"{tool_name}:{digest}"

    # ---------- 维护 ----------

    def clear(self) -> None:
        """清空缓存（测试用）。"""
        self._cache.clear()

    def stats(self) -> dict:
        """返回缓存统计。"""
        return {
            "enabled": self.enabled,
            "cache_size": len(self._cache),
        }


# ============================================================
# 工厂
# ============================================================


def create_idempotency_middleware(
    enabled: bool = True,
) -> IdempotencyMiddleware:
    """创建幂等性中间件。"""
    return IdempotencyMiddleware(enabled=enabled)
