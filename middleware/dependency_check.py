"""依赖影响检查中间件。

同时实现同步和异步版本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from codebase.impact import ImpactAnalyzer


@dataclass
class DependencyCheckConfig:
    enabled: bool = True
    intercept_tools: set[str] = field(
        default_factory=lambda: {"edit_file", "tx_edit", "apply_patch"}
    )
    max_affected: int = 15
    warn_threshold: int = 20


_FUNC_DEF_RE = re.compile(r"^\s*def\s+(\w+)", re.MULTILINE)
_CLASS_DEF_RE = re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)


class DependencyCheckMiddleware(AgentMiddleware):
    """编辑前依赖影响检查。"""

    name: str = "DependencyCheckMiddleware"

    def __init__(
        self,
        impact_analyzer: ImpactAnalyzer,
        config: DependencyCheckConfig | None = None,
    ):
        super().__init__()
        self.analyzer = impact_analyzer
        self.config = config or DependencyCheckConfig()

    # ---------- 同步 ----------

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        if not tool_call:
            return handler(request)

        tool_name = tool_call.get("name")
        if tool_name not in self.config.intercept_tools or not self.config.enabled:
            return handler(request)

        result = handler(request)
        return self._attach_hint(result, tool_call)

    # ---------- 异步 ----------

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or request.get("tool_call")
        if not tool_call:
            return await handler(request)

        tool_name = tool_call.get("name")
        if tool_name not in self.config.intercept_tools or not self.config.enabled:
            return await handler(request)

        result = await handler(request)
        return self._attach_hint(result, tool_call)

    # ---------- 内部 ----------

    def _attach_hint(self, result, tool_call: dict):
        args = tool_call.get("args", {})
        impacted = self._extract_and_analyze(args)

        if not impacted:
            return result

        hint = self._format_hint(impacted)

        if isinstance(result, ToolMessage):
            result.content = f"{result.content}\n\n{hint}"
            return result
        elif isinstance(result, str):
            return result + "\n\n" + hint
        else:
            return result

    def _extract_and_analyze(self, args: dict) -> dict:
        symbols: set[str] = set()

        for key in ("old_string", "new_string", "content"):
            text = args.get(key, "")
            if not isinstance(text, str):
                continue
            for m in _FUNC_DEF_RE.finditer(text):
                symbols.add(m.group(1))
            for m in _CLASS_DEF_RE.finditer(text):
                symbols.add(m.group(1))

        if not symbols:
            return {}

        impacts = {}
        for sym in list(symbols)[:5]:
            report = self.analyzer.analyze(sym, max_depth=2)
            if report.total_impact > 0:
                impacts[sym] = report

        return impacts

    def _format_hint(self, impacts: dict) -> str:
        lines = ["⚠️  **依赖影响检查**"]

        for sym, report in impacts.items():
            def_file = report.definition[0][0] if report.definition else ""
            affected = [f for f in report.affected_files if f != def_file]
            if not affected:
                continue

            lines.append(f"\n修改 `{sym}` 可能影响以下文件:")
            for f in affected[: self.config.max_affected]:
                lines.append(f"  - {f}")
            if len(affected) > self.config.max_affected:
                lines.append(f"  ... 还有 {len(affected) - self.config.max_affected} 个")

            if len(affected) > self.config.warn_threshold:
                lines.append(
                    f"  ⚠️  影响文件数超过 {self.config.warn_threshold}，"
                    f"建议使用事务（begin_transaction）批量修改"
                )

        lines.append(
            "\n建议: 使用 `begin_transaction` 开启事务，同时修改以上所有文件以保证接口一致性。"
        )
        return "\n".join(lines)


def create_dependency_check_middleware(impact_analyzer: ImpactAnalyzer):
    return DependencyCheckMiddleware(
        impact_analyzer=impact_analyzer,
        config=DependencyCheckConfig(),
    )
