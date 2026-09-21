"""熔断器中间件。

同时实现同步和异步版本的方法，兼容 invoke / ainvoke。

阈值策略：
- 只读工具（read_file / grep_search / glob_files / ls_dir / ...）：
  重复调用很正常，阈值放宽到 20 次。
- 写工具（edit_file / write_file / execute / apply_patch / ...）：
  重复写很可疑，阈值收紧到 5 次。
- 未知工具：走默认阈值（8 次）。
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware

from sandbox.error_classifier import ErrorClass, classify_error, suggest_recovery


class CircuitBreakerError(Exception):
    """熔断触发。"""

    pass


# ---------- 工具分类 ----------

# 只读工具：重复调用正常，阈值放宽
_READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "grep_search",
        "glob_files",
        "ls_dir",
        "sandbox_read",
        "sandbox_grep",
        "find_definition",
        "find_callers",
        "find_circular_deps",
        "repo_map",
        "analyze_impact",
        "search_tools",
        "load_skill",
        "search_code",
        "index_status",
    }
)

# 写工具：重复写可疑，阈值收紧
_WRITE_TOOLS = frozenset(
    {
        "edit_file",
        "write_file",
        "apply_patch",
        "execute",
        "sandbox_write",
        "tx_edit",
        "tx_commit",
        "begin_transaction",
        "run_tests",
        "run_lint",
    }
)


@dataclass
class CircuitBreakerConfig:
    """熔断器配置。

    阈值策略：
    - read_only_max_repeats：只读工具的重复调用阈值（默认 20）
    - write_max_repeats：写工具的重复调用阈值（默认 5）
    - default_max_repeats：未知工具的阈值（默认 8）

    兼容旧字段：
    - max_repeats：如果设置，会覆盖以上三个（所有工具用同一阈值）
    """

    # 新字段：按工具分类的阈值
    read_only_max_repeats: int = 20
    write_max_repeats: int = 5
    default_max_repeats: int = 8

    # 兼容旧字段：如果非 None，会覆盖以上三个
    max_repeats: int | None = None

    # 失败相关（保持原样）
    max_consecutive_failures: int = 3
    max_retries_for_retryable: int = 5
    allow_manual_reset: bool = True

    # 可自定义的工具分类（覆盖默认）
    read_only_tools: frozenset[str] = field(default_factory=lambda: _READ_ONLY_TOOLS)
    write_tools: frozenset[str] = field(default_factory=lambda: _WRITE_TOOLS)

    def threshold_for(self, tool_name: str) -> int:
        """返回指定工具的重复调用阈值。"""
        # 兼容旧字段：如果 max_repeats 显式设置，所有工具都用它
        if self.max_repeats is not None:
            return self.max_repeats
        if tool_name in self.read_only_tools:
            return self.read_only_max_repeats
        if tool_name in self.write_tools:
            return self.write_max_repeats
        return self.default_max_repeats


class CircuitBreakerMiddleware(AgentMiddleware):
    """熔断器中间件。"""

    name: str = "CircuitBreakerMiddleware"

    def __init__(self, config: CircuitBreakerConfig | None = None):
        super().__init__()
        self.config = config or CircuitBreakerConfig()
        self.call_fingerprints: Counter[str] = Counter()
        self.consecutive_failures: dict[str, int] = defaultdict(int)
        self.retry_counters: dict[str, int] = defaultdict(int)
        self.breaker_events: list[dict] = []

    # ---------- 同步 ----------

    def wrap_tool_call(self, request, handler):
        tool_call, fp = self._pre_check(request)
        if not tool_call:
            return handler(request)

        try:
            result = handler(request)
            self._on_success(fp)
            return result
        except Exception as e:
            self._on_failure(e, fp, tool_call, is_async=False)

    # ---------- 异步 ----------

    async def awrap_tool_call(self, request, handler):
        tool_call, fp = self._pre_check(request)
        if not tool_call:
            return await handler(request)

        try:
            result = await handler(request)
            self._on_success(fp)
            return result
        except Exception as e:
            self._on_failure(e, fp, tool_call, is_async=True)

    # ---------- 内部 ----------

    def _pre_check(self, request):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        if not tool_call:
            return None, ""

        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        fp = self._fingerprint(tool_name, args)

        self.call_fingerprints[fp] += 1
        threshold = self.config.threshold_for(tool_name)

        if self.call_fingerprints[fp] > threshold:
            self._record_breaker("repeat", tool_name, fp, self.call_fingerprints[fp])
            raise CircuitBreakerError(
                f"熔断：{tool_name} 相同调用已重复 {self.call_fingerprints[fp]} 次"
                f"（阈值 {threshold}）。"
                f"请分析错误原因，换用不同策略或报告无法完成。"
            )

        return tool_call, fp

    def _on_success(self, fp: str) -> None:
        self.consecutive_failures[fp] = 0
        self.retry_counters[fp] = 0

    def _on_failure(self, e: Exception, fp: str, tool_call: dict, is_async: bool) -> None:
        tool_name = tool_call.get("name", "")
        error_text = str(e)
        error_class = classify_error(error_text)
        recovery_hint = suggest_recovery(error_text, tool_name)

        self.consecutive_failures[fp] += 1
        if self.consecutive_failures[fp] >= self.config.max_consecutive_failures:
            self._record_breaker(
                "consecutive_failures", tool_name, fp, self.consecutive_failures[fp]
            )
            raise CircuitBreakerError(
                f"熔断：{tool_name} 连续失败 {self.consecutive_failures[fp]} 次。\n"
                f"错误类别: {error_class.value}\n"
                f"错误信息: {error_text[:200]}\n"
                f"恢复建议: {recovery_hint}"
            )

        if error_class == ErrorClass.RETRYABLE:
            self.retry_counters[fp] += 1
            if self.retry_counters[fp] > self.config.max_retries_for_retryable:
                self._record_breaker("excessive_retries", tool_name, fp, self.retry_counters[fp])
                raise CircuitBreakerError(
                    f"熔断：可重试错误已重试 {self.retry_counters[fp]} 次仍未成功。"
                    f"请报告服务不可用或换用替代方案。"
                )

        # 把错误分类和恢复建议附加到异常信息
        raise RuntimeError(
            f"{error_text}\n[错误类别: {error_class.value}]\n[恢复建议: {recovery_hint}]"
        ) from e

    def _fingerprint(self, tool_name: str, args: dict) -> str:
        key_args = {}
        for k in ("path", "command", "symbol_name", "query", "pattern"):
            if k in args:
                v = args[k]
                if isinstance(v, str) and len(v) > 60:
                    v = v[:60] + "..."
                key_args[k] = v
        args_str = json.dumps(key_args, sort_keys=True, ensure_ascii=False)
        return f"{tool_name}({args_str})"

    def _record_breaker(self, reason: str, tool_name: str, fp: str, count: int) -> None:
        self.breaker_events.append(
            {
                "timestamp": time.time(),
                "reason": reason,
                "tool_name": tool_name,
                "fingerprint": fp,
                "count": count,
            }
        )

    def reset(self) -> None:
        self.call_fingerprints.clear()
        self.consecutive_failures.clear()
        self.retry_counters.clear()

    def stats(self) -> dict:
        return {
            "breaker_events": len(self.breaker_events),
            "recent_events": self.breaker_events[-5:],
            "active_fingerprints": len(self.call_fingerprints),
        }
