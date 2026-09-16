"""上下文用量 API。

提供 Token 消耗、缓存命中率、压缩事件等信息。
"""

from __future__ import annotations

import os
import random

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


AGENT_MODE = os.getenv("AGENT_MODE", "mock").lower()


@router.get("/context")
async def get_context_metrics(session_id: str = Query(...)):
    """获取会话的上下文用量。

    mock 模式返回模拟数据（每次略有波动，模拟真实场景）。
    real 模式从 AgentRuntime 读取真实指标。
    """
    if AGENT_MODE == "mock":
        return _mock_metrics()
    return _real_metrics(session_id)


def _mock_metrics() -> dict:
    """模拟数据。数值随机波动，让前端调试时能看到变化。"""
    used = random.randint(8000, 60000)
    max_tokens = 200_000
    return {
        "used_tokens": used,
        "max_tokens": max_tokens,
        "cache_hit_rate": round(random.uniform(0.45, 0.85), 3),
        "compaction_events": {
            "L1": random.randint(0, 3),
            "L2": random.randint(0, 2),
            "L3": random.randint(0, 1),
            "L4": random.randint(0, 1),
            "L5": random.randint(0, 1),
        },
        "offloaded_files": [
            f".context_offload/grep_{i:03d}.txt" for i in range(random.randint(0, 3))
        ],
        "total_cost_usd": round(random.uniform(0.01, 0.25), 4),
    }


def _real_metrics(session_id: str) -> dict:
    """真实数据。需要从 API server 的全局 runtime 读取。

    TODO: 等 AgentRuntime 暴露 metrics 接口后启用真实读数。
    当前实现与 mock 一致，避免前端字段缺失导致崩溃。
    """
    # 延迟导入，避免循环依赖
    from api.server import _runtimes

    rt = _runtimes.get(session_id)
    if rt is None:
        return _mock_metrics()

    # 真实指标采集的接入点：
    # 等 AgentRuntime 提供 get_metrics() 或 metrics_snapshot 属性后，
    # 在这里读取；现在直接回退到 mock。
    # if hasattr(rt, "metrics_snapshot"):
    #     return rt.metrics_snapshot()
    return _mock_metrics()
