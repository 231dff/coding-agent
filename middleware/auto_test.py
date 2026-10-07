"""P1-1: 写操作后自动跑测试的中间件。

关键设计：
  - LangChain 1.4 的 wrap_tool_call 无法向对话注入额外消息，
    所以把测试结果附加到原工具的返回文本里。
  - 首次触发时探测沙箱是否有测试基础设施（pytest + tests/ 目录），
    没有就静默跳过，避免污染轨迹。
  - 探测结果通过 logging.debug 记录，默认静音。
"""

from __future__ import annotations

import logging
import time

from langchain.agents.middleware import AgentMiddleware

# 模块级 logger：默认 WARNING 级，探测信息不会刷屏
log = logging.getLogger("autotest")

WRITE_TOOLS = {
    "write_file",
    "edit_file",
    "apply_patch",
    "sandbox_write",
}

AUTO_TEST_MARKER = "=== AutoTest Results ==="

# 探测命令：同时检查 pytest 和 tests/ 目录是否存在
DEFAULT_PROBE_CMD = (
    "if command -v pytest >/dev/null 2>&1 && [ -d tests ]; "
    "then echo __PROBE_YES__; else echo __PROBE_NO__; fi"
)


class AutoTestMiddleware(AgentMiddleware):
    """写操作后自动跑测试，把结果附加到原工具的返回里。"""

    name: str = "AutoTestMiddleware"

    def __init__(
        self,
        test_command: str = "pytest tests/ -v --tb=short",
        enabled: bool = True,
        cooldown_s: float = 0.0,
        probe_command: str = DEFAULT_PROBE_CMD,
    ):
        super().__init__()
        self.test_command = test_command
        self.enabled = enabled
        self.cooldown_s = cooldown_s
        self.probe_command = probe_command
        self._last_test_at: float = 0.0
        self._run_tests_tool = None
        # 探测结果缓存：None=未探测, True=有测试设施, False=没有
        self._probe_result: bool | None = None

    def bind_run_tests_tool(self, tool) -> None:
        self._run_tests_tool = tool

    # ============================================================
    # 探测：项目有没有测试基础设施
    # ============================================================

    def _probe(self) -> bool:
        """探测项目是否有测试设施。结果缓存，只跑一次。"""
        if self._probe_result is not None:
            return self._probe_result
        if self._run_tests_tool is None:
            self._probe_result = False
            return False

        try:
            out = self._run_tests_tool.invoke({"command": self.probe_command})
            self._probe_result = "__PROBE_YES__" in str(out)
        except Exception:
            self._probe_result = False

        # ★ 静音：默认 WARNING 级不显示；LOG_LEVEL=DEBUG 可见
        log.debug(
            "probe_result=%s cmd=%s",
            self._probe_result,
            self.probe_command[:60],
        )
        return self._probe_result

    # ============================================================
    # 同步
    # ============================================================

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None)
        tool_name = self._extract_tool_name(tool_call)

        result = handler(request)

        if not self._should_trigger(tool_name):
            return result

        test_output = self._run_tests()
        return self._append_to_result(result, test_output, tool_name)

    # ============================================================
    # 异步
    # ============================================================

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None)
        tool_name = self._extract_tool_name(tool_call)

        result = await handler(request)

        if not self._should_trigger(tool_name):
            return result

        test_output = await self._run_tests_async()
        return self._append_to_result(result, test_output, tool_name)

    # ============================================================
    # 内部
    # ============================================================

    @staticmethod
    def _extract_tool_name(tool_call):
        if tool_call is None:
            return ""
        if isinstance(tool_call, dict):
            return tool_call.get("name", "")
        return getattr(tool_call, "name", "")

    def _should_trigger(self, tool_name: str) -> bool:
        """判定是否应该触发自动测试。"""
        if not self.enabled:
            return False
        if tool_name not in WRITE_TOOLS:
            return False
        if self._run_tests_tool is None:
            return False

        # 探测失败 → 静默跳过
        if not self._probe():
            return False

        # 冷却
        now = time.time()
        if now - self._last_test_at < self.cooldown_s:
            return False
        self._last_test_at = now
        return True

    def _run_tests(self) -> str:
        try:
            return str(self._run_tests_tool.invoke({"command": self.test_command}))
        except Exception as e:
            return f"[AutoTest] 调用失败: {e}"

    async def _run_tests_async(self) -> str:
        try:
            return str(await self._run_tests_tool.ainvoke({"command": self.test_command}))
        except Exception as e:
            return f"[AutoTest] 调用失败: {e}"

    @staticmethod
    def _append_to_result(result, test_output: str, tool_name: str):
        original = ""
        if hasattr(result, "content"):
            c = result.content
            original = c if isinstance(c, str) else str(c)

        combined = f"{original}\n\n{AUTO_TEST_MARKER}\n[工具] {tool_name}\n{test_output}"

        if hasattr(result, "content"):
            result.content = combined
        return result
