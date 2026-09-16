"""Agent 状态栏。

缓存友好设计：
- 只保留**状态变化**时才变的字段
- 移除所有时间戳类字段（每轮变化会击穿缓存）
- 键值对形式，渲染结果可复现
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal


UpdateMode = Literal["replace", "persistent"]


@dataclass
class TodoItem:
    """TODO 列表项。"""
    id: str
    text: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_line(self) -> str:
        return f"[{self.status}] {self.id}: {self.text}"


class AgentStatusBar:
    """Agent 状态栏。"""

    def __init__(self, mode: UpdateMode = "persistent"):
        self.mode = mode
        self.session_start = time.time()

        self.tool_counters: Counter[str] = Counter()
        self.tool_failures: dict[str, int] = defaultdict(int)
        self.last_tool_time: float = self.session_start

        self.todos: dict[str, TodoItem] = {}
        self._todo_seq = 0

        self.cwd: str = "/workspace"
        self.git_branch: str = ""
        self.git_status: str = ""

        self.available_skills: list[str] = []

        # 缓存：上次 render 结果与输入指纹，只有指纹变了才重新生成
        self._last_render_input: str = ""
        self._last_render_output: str = ""

    # ---------- 记录接口 ----------

    def record_tool_call(
        self,
        tool_name: str,
        args: dict,
        success: bool,
    ) -> None:
        fp = self._fingerprint(tool_name, args)
        self.tool_counters[fp] += 1
        self.last_tool_time = time.time()

        if success:
            self.tool_failures[fp] = 0
        else:
            self.tool_failures[fp] += 1

    def update_cwd(self, cwd: str) -> None:
        self.cwd = cwd

    def update_git(self, branch: str, status: str = "") -> None:
        self.git_branch = branch
        self.git_status = status

    def set_skills(self, skills: list[str]) -> None:
        self.available_skills = skills

    # ---------- TODO 管理 ----------

    def todo_add(self, text: str) -> str:
        self._todo_seq += 1
        todo_id = f"T{self._todo_seq}"
        self.todos[todo_id] = TodoItem(id=todo_id, text=text, status="pending")
        return todo_id

    def todo_update(self, todo_id: str, status: str) -> bool:
        if todo_id not in self.todos:
            return False
        item = self.todos[todo_id]
        item.status = status  # type: ignore
        item.updated_at = time.time()
        return True

    def todo_rewrite(self, items: list[dict]) -> None:
        self.todos.clear()
        for i, item in enumerate(items, 1):
            todo_id = f"T{i}"
            self.todos[todo_id] = TodoItem(
                id=todo_id,
                text=item["text"],
                status=item.get("status", "pending"),
            )
        self._todo_seq = len(items)

    # ---------- 渲染 ----------

    def render(self) -> str:
        """渲染为可注入文本。

        **缓存友好**：只有状态发生变化时，输出才会不同。
        不包含任何时间戳/耗时类字段。
        """
        # 先算一个输入指纹，与上次相同则直接返回缓存
        fingerprint = self._build_fingerprint()
        if fingerprint == self._last_render_input:
            return self._last_render_output

        lines = ["<agent_status>"]

        # 1. 工具调用计数（只列出 ≥ 2 次的，避免冗长）
        if self.tool_counters:
            lines.append("tool_calls:")
            shown = 0
            for k, v in self.tool_counters.most_common():
                if v < 2:
                    break
                fails = self.tool_failures.get(k, 0)
                fail_str = f" (failures: {fails})" if fails else ""
                lines.append(f"  {k}: {v}{fail_str}")
                shown += 1
                if shown >= 10:
                    break

        # 2. TODO 列表
        if self.todos:
            lines.append("todo:")
            order = {"in_progress": 0, "pending": 1, "completed": 2, "cancelled": 3}
            sorted_todos = sorted(
                self.todos.values(), key=lambda t: order.get(t.status, 9)
            )
            for item in sorted_todos[:15]:
                lines.append(f"  {item.to_line()}")

        # 3. 环境状态（cwd / git 分支变化频率低）
        lines.append(f"cwd: {self.cwd}")
        if self.git_branch:
            lines.append(f"git_branch: {self.git_branch}")

        # 4. 可用技能
        if self.available_skills:
            lines.append(
                f"available_skills: {', '.join(self.available_skills[:20])}"
            )

        lines.append("</agent_status>")
        output = "\n".join(lines)

        # 缓存本次结果
        self._last_render_input = fingerprint
        self._last_render_output = output

        return output

    # ---------- 内部 ----------

    def _build_fingerprint(self) -> str:
        """用所有影响输出的状态字段计算指纹。"""
        parts = [
            # 工具计数（只取 ≥2 次的）
            "|".join(
                f"{k}={v}:{self.tool_failures.get(k, 0)}"
                for k, v in sorted(self.tool_counters.items())
                if v >= 2
            ),
            # TODO
            "|".join(
                f"{t.id}:{t.status}:{t.text}"
                for t in sorted(self.todos.values(), key=lambda x: x.id)
            ),
            # 环境
            self.cwd,
            self.git_branch,
            # 技能
            ",".join(self.available_skills),
        ]
        return "::".join(parts)

    def _fingerprint(self, tool_name: str, args: dict) -> str:
        """生成工具调用的稳定指纹。"""
        key_args = {}
        for k in ("path", "command", "symbol_name", "query", "pattern"):
            if k in args:
                v = args[k]
                if isinstance(v, str) and len(v) > 60:
                    v = v[:60] + "..."
                key_args[k] = v
        args_str = json.dumps(key_args, sort_keys=True, ensure_ascii=False)
        return f"{tool_name}({args_str})"

    def _fmt_duration(self, seconds: float) -> str:
        # 保留此方法以便向后兼容，但 render 不再调用
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds // 60)}m{int(seconds % 60)}s"
        return f"{int(seconds // 3600)}h{int((seconds % 3600) // 60)}m"

    def reset(self) -> None:
        self.__init__(self.mode)  # type: ignore