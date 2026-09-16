"""条件化思考中间件分类逻辑测试。

测试目标：
- 强关词命中 → 关思考
- 强开词命中 → 开思考
- 长度启发生效
- 多子问题识别
- 默认保守（未命中规则 → 开思考）
"""

from __future__ import annotations

import pytest

from middleware.thinking_router import (
    ThinkingRouterConfig,
    classify_task,
)


@pytest.fixture
def cfg() -> ThinkingRouterConfig:
    return ThinkingRouterConfig()


# ============================================================
# 强关词
# ============================================================


@pytest.mark.parametrize(
    "text",
    [
        "读一下 README",
        "看看 src/main.py",
        "列出所有 Python 文件",
        "查看项目结构",
        "跑一下测试",
        "执行 pytest",
        "改一下 config.py 第 42 行",
        "加上一个函数",
        "删掉这行",
    ],
)
def test_strong_off_keywords(text, cfg):
    """命中强关词 → 应关思考。"""
    need, reason = classify_task(text, cfg)
    assert need is False, f"期望关思考，实际开：{text}（{reason}）"


# ============================================================
# 强开词
# ============================================================


@pytest.mark.parametrize(
    "text",
    [
        "为什么这个函数返回 None",
        "分析这个项目的模块结构",
        "帮我设计一个缓存层",
        "诊断一下登录失败的原因",
        "优化这个查询的性能",
        "重构这段代码",
        "解释一下这个架构",
        "比较这两个方案",
        "权衡一下性能与复杂度",
    ],
)
def test_strong_on_keywords(text, cfg):
    """命中强开词 → 应开思考。"""
    need, reason = classify_task(text, cfg)
    assert need is True, f"期望开思考，实际关：{text}（{reason}）"


# ============================================================
# 长度启发
# ============================================================


def test_short_message_no_keywords(cfg):
    """短消息且无关键词 → 默认关。"""
    need, _ = classify_task("嗯", cfg)
    assert need is False


def test_long_message(cfg):
    """长消息 → 默认开。"""
    long_text = "帮我看看这段代码" + "非常长的描述" * 30
    need, _ = classify_task(long_text, cfg)
    assert need is True


# ============================================================
# 多子问题
# ============================================================


def test_multiple_subquestions_by_comma(cfg):
    """两个顿号 → 多子问题 → 开。"""
    need, reason = classify_task("先读一下 README、看一下 main.py、最后跑一下测试", cfg)
    assert need is True, f"多子问题应开思考，实际关（{reason}）"


# ============================================================
# strategy 强制覆盖
# ============================================================


def test_strategy_always():
    cfg = ThinkingRouterConfig(strategy="always")
    need, reason = classify_task("读一下 README", cfg)
    assert need is True
    assert "always" in reason


def test_strategy_never():
    cfg = ThinkingRouterConfig(strategy="never")
    need, reason = classify_task("为什么这个函数返回 None", cfg)
    assert need is False
    assert "never" in reason


# ============================================================
# 返回格式
# ============================================================


def test_returns_tuple(cfg):
    """返回值必须是 (bool, str)。"""
    result = classify_task("读一下 README", cfg)
    assert isinstance(result, tuple)
    assert len(result) == 2
    need, reason = result
    assert isinstance(need, bool)
    assert isinstance(reason, str)
    assert reason  # 非空


# ============================================================
# 空输入
# ============================================================


def test_empty_input(cfg):
    """空字符串不应崩溃。"""
    need, _ = classify_task("", cfg)
    # 空消息 < 30 字符，判定为简单
    assert need is False
