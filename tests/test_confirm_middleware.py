"""middleware/confirm_middleware.py 单元测试。

实际接口（v1）：
  - ConfirmMiddleware(enabled=True)  # 只有 enabled 参数
  - CONFIRM_TOOLS / DANGEROUS_CMD_PATTERNS
  - _should_ask / _ask_user / wrap_tool_call / awrap_tool_call
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from middleware.confirm_middleware import (
    CONFIRM_TOOLS,
    DANGEROUS_CMD_PATTERNS,
    ConfirmMiddleware,
    create_confirm_middleware,
)

# ============================================================
# helpers
# ============================================================


def make_request(tool_name: str, **args):
    """构造一个最小 request（带 tool_call dict）。"""
    return SimpleNamespace(
        tool_call={
            "name": tool_name,
            "args": args,
            "id": f"call-{tool_name}",
        }
    )


@pytest.fixture
def handler():
    def _h(request):
        return ToolMessage(
            content="ok",
            tool_call_id=request.tool_call["id"],
            status="success",
        )
    return _h


@pytest.fixture
def mw():
    return ConfirmMiddleware(enabled=True)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_EVAL_MODE", raising=False)
    monkeypatch.delenv("AGENT_CONFIRM", raising=False)


# ============================================================
# 常量
# ============================================================


def test_confirm_tools_contains_core():
    assert "write_file" in CONFIRM_TOOLS
    assert "edit_file" in CONFIRM_TOOLS
    assert "apply_patch" in CONFIRM_TOOLS
    assert "execute" in CONFIRM_TOOLS
    assert "run_tests" in CONFIRM_TOOLS


def test_dangerous_patterns_contains_rm_rf():
    import re
    blob = "rm -rf /tmp/foo"
    assert any(re.search(p, blob) for p in DANGEROUS_CMD_PATTERNS)


def test_dangerous_patterns_ignores_ls():
    import re
    blob = "ls -la"
    assert not any(re.search(p, blob) for p in DANGEROUS_CMD_PATTERNS)


# ============================================================
# _should_ask — 基础开关
# ============================================================


def test_disabled_does_not_ask():
    mw = ConfirmMiddleware(enabled=False)
    assert mw._should_ask(make_request("write_file")) is False


def test_allow_all_short_circuits(mw):
    mw._allow_all = True
    assert mw._should_ask(make_request("write_file")) is False
    assert mw._should_ask(make_request("execute", command="rm -rf /")) is False


def test_eval_mode_never_asks(mw, monkeypatch):
    monkeypatch.setenv("AGENT_EVAL_MODE", "true")
    assert mw._should_ask(make_request("write_file")) is False


def test_global_off_never_asks(mw, monkeypatch):
    monkeypatch.setenv("AGENT_CONFIRM", "off")
    assert mw._should_ask(make_request("write_file")) is False


# ============================================================
# _should_ask — 工具分类
# ============================================================


def test_write_tool_asks(mw):
    assert mw._should_ask(make_request("write_file", path="a.py")) is True
    assert mw._should_ask(make_request("edit_file", path="a.py")) is True
    assert mw._should_ask(make_request("apply_patch", patch="x")) is True


def test_run_tests_asks(mw):
    assert mw._should_ask(make_request("run_tests", command="pytest")) is True


def test_non_confirm_tool_never_asks(mw):
    """不在 CONFIRM_TOOLS 里的工具永远不问（如 read_file / grep_search）。"""
    assert mw._should_ask(make_request("read_file", path="a.py")) is False
    assert mw._should_ask(make_request("grep_search", pattern="TODO")) is False
    assert mw._should_ask(make_request("repo_map")) is False


# ============================================================
# _should_ask — execute 特殊处理
# ============================================================


def test_execute_safe_cmd_does_not_ask(mw):
    assert mw._should_ask(make_request("execute", command="ls -la")) is False
    assert mw._should_ask(make_request("execute", command="python main.py")) is False
    assert mw._should_ask(make_request("execute", command="pytest -v")) is False


def test_execute_rm_rf_asks(mw):
    assert mw._should_ask(make_request("execute", command="rm -rf /tmp/x")) is True


def test_execute_sudo_asks(mw):
    assert mw._should_ask(make_request("execute", command="sudo apt update")) is True


def test_execute_git_push_asks(mw):
    assert mw._should_ask(make_request("execute", command="git push origin main")) is True


def test_execute_git_reset_hard_asks(mw):
    assert mw._should_ask(make_request("execute", command="git reset --hard HEAD~1")) is True


def test_execute_pip_uninstall_asks(mw):
    assert mw._should_ask(make_request("execute", command="pip uninstall requests")) is True


def test_execute_chmod_777_asks(mw):
    assert mw._should_ask(make_request("execute", command="chmod 777 /tmp/x")) is True


def test_execute_docker_rm_asks(mw):
    assert mw._should_ask(make_request("execute", command="docker rm my-container")) is True


# ============================================================
# _should_ask — 白名单
# ============================================================


def test_whitelist_skips(mw):
    mw._allow_tools.add("write_file")
    assert mw._should_ask(make_request("write_file")) is False


def test_whitelist_only_affects_that_tool(mw):
    mw._allow_tools.add("write_file")
    assert mw._should_ask(make_request("write_file")) is False
    assert mw._should_ask(make_request("edit_file")) is True


# ============================================================
# wrap_tool_call — 用户响应
# ============================================================


def test_user_approves_runs_handler(mw, handler, monkeypatch):
    monkeypatch.setattr(
        "middleware.confirm_middleware.Prompt.ask",
        lambda *a, **kw: "y",
    )
    result = mw.wrap_tool_call(make_request("write_file"), handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "success"
    assert result.content == "ok"


def test_user_approves_all_adds_to_whitelist(mw, handler, monkeypatch):
    monkeypatch.setattr(
        "middleware.confirm_middleware.Prompt.ask",
        lambda *a, **kw: "a",
    )
    mw.wrap_tool_call(make_request("write_file"), handler)
    assert "write_file" in mw._allow_tools


def test_user_rejects_returns_error_message(mw, handler, monkeypatch):
    """用户拒绝 → handler 不被调用，返回 status=error。"""
    monkeypatch.setattr(
        "middleware.confirm_middleware.Prompt.ask",
        lambda *a, **kw: "n",
    )

    called = {"n": 0}

    def _tracking(request):
        called["n"] += 1
        return handler(request)

    result = mw.wrap_tool_call(make_request("write_file"), _tracking)

    assert called["n"] == 0
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "拒绝" in result.content


def test_keyboard_interrupt_treated_as_reject(mw, handler, monkeypatch):
    def _raise(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("middleware.confirm_middleware.Prompt.ask", _raise)
    result = mw.wrap_tool_call(make_request("write_file"), handler)
    assert result.status == "error"


# ============================================================
# 不询问时透传
# ============================================================


def test_readonly_tool_passes_through(mw, handler):
    called = {"n": 0}

    def _tracking(request):
        called["n"] += 1
        return handler(request)

    mw.wrap_tool_call(make_request("read_file"), _tracking)
    assert called["n"] == 1


def test_safe_execute_passes_through(mw, handler):
    called = {"n": 0}

    def _tracking(request):
        called["n"] += 1
        return handler(request)

    mw.wrap_tool_call(make_request("execute", command="ls"), _tracking)
    assert called["n"] == 1


def test_whitelisted_tool_passes_through(mw, handler):
    mw._allow_tools.add("write_file")
    called = {"n": 0}

    def _tracking(request):
        called["n"] += 1
        return handler(request)

    mw.wrap_tool_call(make_request("write_file"), _tracking)
    assert called["n"] == 1


# ============================================================
# 异步
# ============================================================


@pytest.mark.asyncio
async def test_awrap_tool_call_equivalent(mw, monkeypatch):
    monkeypatch.setattr(
        "middleware.confirm_middleware.Prompt.ask",
        lambda *a, **kw: "y",
    )

    async def a_handler(request):
        return ToolMessage(
            content="async ok",
            tool_call_id=request.tool_call["id"],
            status="success",
        )

    result = await mw.awrap_tool_call(make_request("write_file"), a_handler)
    assert result.content == "async ok"


@pytest.mark.asyncio
async def test_awrap_tool_call_rejects(mw, monkeypatch):
    monkeypatch.setattr(
        "middleware.confirm_middleware.Prompt.ask",
        lambda *a, **kw: "n",
    )

    async def a_handler(request):
        return ToolMessage(
            content="should not run",
            tool_call_id=request.tool_call["id"],
        )

    result = await mw.awrap_tool_call(make_request("write_file"), a_handler)
    assert result.status == "error"


# ============================================================
# 工厂
# ============================================================


def test_factory_returns_instance():
    mw = create_confirm_middleware(enabled=True)
    assert isinstance(mw, ConfirmMiddleware)
    assert mw.enabled is True


def test_factory_disabled():
    mw = create_confirm_middleware(enabled=False)
    assert mw.enabled is False
