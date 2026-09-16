"""指标采集中间件。

把每次 LLM 调用和工具调用的数据写入 MetricsStore（SQLite），
并可选通过 on_metric 回调把事件推给上层（用于终端实时显示）。
"""
from __future__ import annotations

import time
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware

from observability.metrics_store import MetricsStore


# ============================================================
# 消息解包
# ============================================================

def _unwrap_message(obj: Any) -> Any:
    """从各种包装对象里取出真正的 AIMessage。"""
    if obj is None:
        return None

    if hasattr(obj, "content") and (
        hasattr(obj, "usage_metadata") or hasattr(obj, "response_metadata")
    ):
        return obj

    if hasattr(obj, "result"):
        inner = obj.result
        if isinstance(inner, list) and inner:
            return _unwrap_message(inner[0])
        if inner is not None:
            return _unwrap_message(inner)

    if isinstance(obj, list) and obj:
        return _unwrap_message(obj[0])

    if hasattr(obj, "messages"):
        msgs = obj.messages
        if isinstance(msgs, list) and msgs:
            return _unwrap_message(msgs[-1])
        if msgs is not None:
            return _unwrap_message(msgs)

    return obj


# ============================================================
# Usage / Model 提取
# ============================================================

def _empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _extract_usage(response: Any) -> dict:
    """从 LangChain 响应里提取 token usage。"""
    if response is None:
        return _empty_usage()

    usage = getattr(response, "usage_metadata", None)

    if usage:
        if isinstance(usage, dict):
            details = usage.get("input_token_details") or {}
            return {
                "input_tokens": usage.get("input_tokens", 0) or 0,
                "output_tokens": usage.get("output_tokens", 0) or 0,
                "cache_read_tokens": details.get("cache_read", 0) or 0,
                "cache_write_tokens": details.get("cache_creation", 0) or 0,
            }

        details = getattr(usage, "input_token_details", None) or {}
        return {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read_tokens": (
                details.get("cache_read", 0) if isinstance(details, dict) else 0
            ),
            "cache_write_tokens": (
                details.get("cache_creation", 0) if isinstance(details, dict) else 0
            ),
        }

    meta = getattr(response, "response_metadata", {}) or {}
    token_usage = meta.get("token_usage") or meta.get("usage") or {}
    prompt_details = token_usage.get("prompt_tokens_details") or {}

    return {
        "input_tokens": token_usage.get("prompt_tokens", 0) or 0,
        "output_tokens": token_usage.get("completion_tokens", 0) or 0,
        "cache_read_tokens": prompt_details.get("cached_tokens", 0) or 0,
        "cache_write_tokens": 0,
    }


def _extract_model_name(response: Any, default: str = "unknown") -> str:
    if response is None:
        return default
    for attr in ("model_name", "model"):
        val = getattr(response, attr, None)
        if val:
            return str(val)
    meta = getattr(response, "response_metadata", {}) or {}
    return meta.get("model_name") or meta.get("model") or default


# ============================================================
# 中间件
# ============================================================

class MetricsMiddleware(AgentMiddleware):
    """指标采集中间件。"""

    name: str = "MetricsMiddleware"

    def __init__(
        self,
        store: MetricsStore | None = None,
        model_name: str = "unknown",
        debug: bool = False,
        on_metric: Callable[[dict], None] | None = None,
    ):
        super().__init__()
        self.store = store or MetricsStore()
        self.default_model_name = model_name
        self.debug = debug
        self.on_metric = on_metric

    # ---------- 模型调用 ----------

    def wrap_model_call(self, request, handler):
        start = time.time()
        result = handler(request)
        self._record_llm(result, time.time() - start)
        return result

    async def awrap_model_call(self, request, handler):
        start = time.time()
        result = await handler(request)
        self._record_llm(result, time.time() - start)
        return result

    # ---------- 工具调用 ----------

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        tool_name = tool_call.get("name", "") if tool_call else ""
        start = time.time()
        try:
            result = handler(request)
            self._record_tool(tool_name, time.time() - start, success=True)
            return result
        except Exception:
            self._record_tool(tool_name, time.time() - start, success=False)
            raise

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        tool_name = tool_call.get("name", "") if tool_call else ""
        start = time.time()
        try:
            result = await handler(request)
            self._record_tool(tool_name, time.time() - start, success=True)
            return result
        except Exception:
            self._record_tool(tool_name, time.time() - start, success=False)
            raise

    # ---------- 内部：LLM ----------

    def _record_llm(self, result: Any, duration_s: float) -> None:
        try:
            if self.debug:
                print(f"[metrics-debug] result type = {type(result)}")

            message = _unwrap_message(result)

            if self.debug and message is not None:
                print(f"[metrics-debug] unwrapped = {type(message)}")
                print(
                    f"[metrics-debug] usage_metadata = "
                    f"{getattr(message, 'usage_metadata', None)}"
                )

            usage = _extract_usage(message)

            # 流式模式下每个 chunk 都会进这里，只有带 usage 的 chunk 才有意义。
            # usage 全 0 就跳过，避免日志和数据库里满是"in=0 out=0"的垃圾。
            total_tokens = (
                usage["input_tokens"]
                + usage["output_tokens"]
                + usage["cache_read_tokens"]
            )
            if total_tokens == 0:
                return

            model = _extract_model_name(message, default=self.default_model_name)
            cost = self._estimate_cost(
                usage["input_tokens"],
                usage["output_tokens"],
                usage["cache_read_tokens"],
            )

            self.store.record_llm(
                model=model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                cache_write_tokens=usage["cache_write_tokens"],
                duration_ms=duration_s * 1000,
                cost_usd=cost,
            )

            try:
                from observability.logger import get_logger
                get_logger("llm").info(
                    "llm_call",
                    model=model,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cache_read=usage["cache_read_tokens"],
                    duration_s=round(duration_s, 3),
                    cost_usd=round(cost, 6),
                )
            except Exception:
                pass

            if self.on_metric:
                try:
                    self.on_metric({
                        "type": "llm",
                        "model": model,
                        "input_tokens": usage["input_tokens"],
                        "output_tokens": usage["output_tokens"],
                        "cache_read": usage["cache_read_tokens"],
                        "duration_s": round(duration_s, 3),
                        "cost_usd": round(cost, 6),
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass

        except Exception as e:
            if self.debug:
                print(f"[metrics-debug] _record_llm 异常: {type(e).__name__}: {e}")

    # ---------- 内部：工具 ----------

    def _record_tool(self, tool_name: str, duration_s: float, success: bool) -> None:
        if not tool_name:
            return
        try:
            self.store.record_tool(
                tool_name=tool_name,
                duration_ms=duration_s * 1000,
                success=success,
            )
            try:
                from observability.logger import get_logger
                get_logger("tool").info(
                    "tool_call",
                    tool=tool_name,
                    duration_s=round(duration_s, 3),
                    success=success,
                )
            except Exception:
                pass

            if self.on_metric:
                try:
                    self.on_metric({
                        "type": "tool",
                        "tool": tool_name,
                        "duration_s": round(duration_s, 3),
                        "success": success,
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- 成本估算 ----------

    def _estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
    ) -> float:
        return (
            input_tokens * 1.60 / 1_000_000
            + output_tokens * 6.40 / 1_000_000
            + cache_read_tokens * 0.16 / 1_000_000
        )