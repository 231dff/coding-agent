"""幂等性中间件测试。"""

from __future__ import annotations

from langchain_core.messages import ToolMessage


class FakeRequest:
    """模拟 LangChain 的 request 对象。"""

    def __init__(self, tool_name: str, args: dict):
        self.tool_call = {"name": tool_name, "args": args}


def test_read_tool_not_cached():
    """只读工具不应被缓存。"""
    from middleware.idempotency import IdempotencyMiddleware

    mw = IdempotencyMiddleware()
    call_count = [0]

    def handler(req):
        call_count[0] += 1
        return ToolMessage(
            content=f"call {call_count[0]}",
            tool_call_id="test",
        )

    req = FakeRequest("read_file", {"path": "a.py"})

    r1 = mw.wrap_tool_call(req, handler)
    r2 = mw.wrap_tool_call(req, handler)

    # 两次都真实执行
    assert call_count[0] == 2


def test_write_tool_cached():
    """写类工具相同参数只执行一次。"""
    from middleware.idempotency import IdempotencyMiddleware

    mw = IdempotencyMiddleware()
    call_count = [0]

    def handler(req):
        call_count[0] += 1
        return ToolMessage(
            content=f"executed {call_count[0]}",
            tool_call_id="test",
        )

    req = FakeRequest("write_file", {"path": "a.py", "content": "x"})

    r1 = mw.wrap_tool_call(req, handler)
    r2 = mw.wrap_tool_call(req, handler)

    # 只执行一次
    assert call_count[0] == 1
    # 返回相同结果
    assert r1.content == r2.content


def test_write_tool_different_args_not_cached():
    """不同参数不应命中同一缓存。"""
    from middleware.idempotency import IdempotencyMiddleware

    mw = IdempotencyMiddleware()
    call_count = [0]

    def handler(req):
        call_count[0] += 1
        return ToolMessage(
            content=f"executed {call_count[0]}",
            tool_call_id="test",
        )

    req1 = FakeRequest("write_file", {"path": "a.py", "content": "x"})
    req2 = FakeRequest("write_file", {"path": "b.py", "content": "y"})

    mw.wrap_tool_call(req1, handler)
    mw.wrap_tool_call(req2, handler)

    assert call_count[0] == 2


def test_disabled_middleware_no_cache():
    """禁用后不做缓存。"""
    from middleware.idempotency import IdempotencyMiddleware

    mw = IdempotencyMiddleware(enabled=False)
    call_count = [0]

    def handler(req):
        call_count[0] += 1
        return ToolMessage(content="ok", tool_call_id="test")

    req = FakeRequest("write_file", {"path": "a.py", "content": "x"})

    mw.wrap_tool_call(req, handler)
    mw.wrap_tool_call(req, handler)

    assert call_count[0] == 2


def test_cache_key_stable():
    """参数顺序不同但值相同 → 命中同一缓存。"""
    from middleware.idempotency import IdempotencyMiddleware

    k1 = IdempotencyMiddleware._make_key("write_file", {"path": "a.py", "content": "x"})
    k2 = IdempotencyMiddleware._make_key("write_file", {"content": "x", "path": "a.py"})
    assert k1 == k2


def test_stats():
    from middleware.idempotency import IdempotencyMiddleware

    mw = IdempotencyMiddleware()
    assert mw.stats()["enabled"] is True
    assert mw.stats()["cache_size"] == 0

    def handler(req):
        return ToolMessage(content="ok", tool_call_id="test")

    req = FakeRequest("write_file", {"path": "a.py", "content": "x"})
    mw.wrap_tool_call(req, handler)
    assert mw.stats()["cache_size"] == 1
