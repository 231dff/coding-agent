"""条件化思考中间件。

思路：根据任务复杂度，决定本轮是否开启模型思考。

简单任务（读取、单点修改、短问句）→ 关思考，快 3–5 倍
复杂任务（推理、规划、多步、设计）→ 保留思考

判断流程（按优先级）：
0. strategy 强制覆盖（always / never）
1. 多子问题（"先X、再Y、最后Z"）→ 开
2. 强关词命中 → 关
3. 强开词命中 → 开
4. 长度启发
5. 默认保守：开思考

Provider 适配：
- moonshot / qwen 系列：extra_body 传 thinking 开关
- anthropic：thinking budget
- 其他：注入 system prompt 提示 [模式: NoThinking]
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware

# ============================================================
# 配置
# ============================================================


@dataclass
class ThinkingRouterConfig:
    """条件化思考配置。"""

    enabled: bool = True
    strategy: str = "auto"  # auto / always / never
    use_llm_fallback: bool = False
    simple_length_threshold: int = 30


# 强制开思考的关键词
_THINKING_KEYWORDS = [
    "为什么",
    "怎么办",
    "原因",
    "分析",
    "推理",
    "设计",
    "规划",
    "架构",
    "方案",
    "思路",
    "优化",
    "重构",
    "改进",
    "提升",
    "调试",
    "排查",
    "诊断",
    "定位",
    "比较",
    "权衡",
    "利弊",
    "区别",
    "对比",
    "解释",
    "原理",
    "机制",
    "怎么实现",
    "所有",
    "全部",
    "批量",
    "一致",
]

# 强制关思考的关键词
_NO_THINKING_KEYWORDS = [
    "读一下",
    "读一下",
    "看看",
    "列出",
    "显示",
    "查看",
    "改一下",
    "改下",
    "加上",
    "加上个",
    "删掉",
    "删除",
    "跑一下",
    "跑下",
    "执行",
    "运行",
    "打开",
    "读取",
]


# ============================================================
# 判断逻辑
# ============================================================


def _match_any(text: str, keywords: list[str]) -> str | None:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def classify_task(user_text: str, cfg: ThinkingRouterConfig) -> tuple[bool, str]:
    """判断是否需要开思考。

    Returns:
        (need_thinking: bool, reason: str)
    """
    if cfg.strategy == "always":
        return True, "strategy=always"
    if cfg.strategy == "never":
        return False, "strategy=never"

    text = user_text.strip()

    # 0. 多子问题优先于一切
    #    "先读X、再看Y、最后跑Z" 虽然含"读一下"，但需要规划
    if text.count("、") >= 2 or text.count("；") >= 2:
        return True, "多子问题"

    # 1. 强关词（"读一下 X" 这种明确指令）
    if len(text) < 100:
        kw = _match_any(text, _NO_THINKING_KEYWORDS)
        if kw:
            return False, f"命中强关词: {kw}"

    # 2. 强开词
    kw = _match_any(text, _THINKING_KEYWORDS)
    if kw:
        return True, f"命中强开词: {kw}"

    # 3. 长度启发
    if len(text) < cfg.simple_length_threshold:
        return False, f"短消息 ({len(text)} 字符)"

    if len(text) > 200:
        return True, f"长消息 ({len(text)} 字符)"

    # 4. 默认保守：开思考
    return True, "默认（未命中规则）"


# ============================================================
# Provider 适配
# ============================================================


def _apply_thinking_off(request, provider: str) -> None:
    """往 request 里注入"关闭思考"的参数。"""
    ms = dict(request.model_settings or {})
    extra_body = dict(ms.get("extra_body") or {})

    if provider in ("moonshot", "qwen", "zhipu", "custom", "openai"):
        extra_body.setdefault("thinking", {"type": "disabled"})
        extra_body.setdefault("enable_thinking", False)
    elif provider == "anthropic":
        extra_body.setdefault("thinking", {"type": "disabled", "budget_tokens": 0})

    if extra_body:
        ms["extra_body"] = extra_body

    request.model_settings = ms


def _apply_thinking_on(request, provider: str) -> None:
    """确保思考开启（部分 Provider 默认关）。"""
    pass


def _inject_mode_hint(request, mode: str) -> None:
    """在最后一条 user 消息里注入 [模式: NoThinking] 之类的提示。"""
    messages = list(request.messages or [])
    if not messages:
        return

    hint = f"\n\n[模式: {mode}]"

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
        if "human" in role or "user" in role:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                messages[i] = msg.model_copy(update={"content": content + hint})
                request.messages = messages
            break


# ============================================================
# 中间件
# ============================================================


class ThinkingRouterMiddleware(AgentMiddleware):
    """条件化思考中间件。"""

    name: str = "ThinkingRouterMiddleware"

    def __init__(
        self,
        provider: str,
        config: ThinkingRouterConfig | None = None,
    ):
        super().__init__()
        self.provider = provider
        self.config = config or ThinkingRouterConfig()

    def modify_model_request(self, request, model):
        return self._route(request)

    async def amodify_model_request(self, request, model):
        return self._route(request)

    def _route(self, request):
        if not self.config.enabled:
            return request

        user_text = self._extract_last_user_text(request.messages)
        if not user_text:
            return request

        need_thinking, reason = classify_task(user_text, self.config)

        if need_thinking:
            _apply_thinking_on(request, self.provider)
        else:
            _apply_thinking_off(request, self.provider)
            _inject_mode_hint(request, "NoThinking")

        if os.getenv("AGENT_DEBUG_THINKING", "").lower() == "true":
            print(
                f"[thinking_router] need_thinking={need_thinking} "
                f"reason={reason!r} provider={self.provider}"
            )

        return request

    @staticmethod
    def _extract_last_user_text(messages) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
            if "human" in role or "user" in role:
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                    return "".join(parts)
        return ""


# ============================================================
# 工厂
# ============================================================


def create_thinking_router_middleware(
    provider: str,
    enabled: bool = True,
    strategy: str = "auto",
) -> ThinkingRouterMiddleware:
    return ThinkingRouterMiddleware(
        provider=provider,
        config=ThinkingRouterConfig(
            enabled=enabled,
            strategy=strategy,
        ),
    )
