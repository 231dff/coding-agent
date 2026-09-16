"""指标采集中间件（异步写）。"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from observability.metrics_store import MetricsStore

# ============================================================
# 异步 MetricsWriter
# ============================================================


class _AsyncMetricsWriter:
    """后台线程批量写 MetricsStore。"""

    def __init__(self, store: MetricsStore, batch_size: int = 50):
        self.store = store
        self.batch_size = batch_size
        self._q: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=10000)
        self._thread = threading.Thread(target=self._run, name="metrics-writer", daemon=True)
        self._thread.start()

    def submit_llm(self, **kw):
        try:
            self._q.put_nowait(("llm", kw))
        except queue.Full:
            pass

    def submit_tool(self, **kw):
        try:
            self._q.put_nowait(("tool", kw))
        except queue.Full:
            pass

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                break
            batch = [item]
            # 尽量攒批
            try:
                while len(batch) < self.batch_size:
                    batch.append(self._q.get_nowait())
            except queue.Empty:
                pass

            try:
                for kind, kw in batch:
                    if kind == "llm":
                        self.store.record_llm(**kw)
                    else:
                        self.store.record_tool(**kw)
            except Exception:
                pass


# ============================================================
# 消息解包
# ============================================================


def _unwrap_message(obj: Any) -> Any:
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


def _empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _extract_usage(response: Any) -> dict:
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
            "cache_read_tokens": (details.get("cache_read", 0) if isinstance(details, dict) else 0),
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
        self.writer = _AsyncMetricsWriter(self.store)

    # ---------- LLM ----------

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

    # ---------- 工具 ----------

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or (
            request.get("tool_call") if hasattr(request, "get") else None
        )
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
        tool_call = getattr(request, "tool_call", None) or (
            request.get("tool_call") if hasattr(request, "get") else None
        )
        tool_name = tool_call.get("name", "") if tool_call else ""
        start = time.time()
        try:
            result = await handler(request)
            self._record_tool(tool_name, time.time() - start, success=True)
            return result
        except Exception:
            self._record_tool(tool_name, time.time() - start, success=False)
            raise

    # ---------- 内部 ----------

    def _record_llm(self, result: Any, duration_s: float) -> None:
        try:
            message = _unwrap_message(result)
            usage = _extract_usage(message)
            total = usage["input_tokens"] + usage["output_tokens"] + usage["cache_read_tokens"]
            if total == 0:
                return

            model = _extract_model_name(message, default=self.default_model_name)
            cost = self._estimate_cost(
                usage["input_tokens"],
                usage["output_tokens"],
                usage["cache_read_tokens"],
            )

            self.writer.submit_llm(
                model=model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                cache_write_tokens=usage["cache_write_tokens"],
                duration_ms=duration_s * 1000,
                cost_usd=cost,
            )

            if self.on_metric:
                try:
                    self.on_metric(
                        {
                            "type": "llm",
                            "model": model,
                            "input_tokens": usage["input_tokens"],
                            "output_tokens": usage["output_tokens"],
                            "cache_read": usage["cache_read_tokens"],
                            "duration_s": round(duration_s, 3),
                            "cost_usd": round(cost, 6),
                            "timestamp": time.time(),
                        }
                    )
                except Exception:
                    pass
        except Exception:
            if self.debug:
                import traceback

                traceback.print_exc()

    def _record_tool(self, tool_name: str, duration_s: float, success: bool) -> None:
        if not tool_name:
            return
        try:
            self.writer.submit_tool(
                tool_name=tool_name,
                duration_ms=duration_s * 1000,
                success=success,
            )
            if self.on_metric:
                try:
                    self.on_metric(
                        {
                            "type": "tool",
                            "tool": tool_name,
                            "duration_s": round(duration_s, 3),
                            "success": success,
                            "timestamp": time.time(),
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

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
