"""LangSmith tracing 接入。

零配置：设置 LANGCHAIN_TRACING_V2=true 后 LangChain 自动上报。
本模块只负责配置校验与手动 trace。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


def is_enabled() -> bool:
    """检查 tracing 是否启用。"""
    return (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
        and bool(os.getenv("LANGCHAIN_API_KEY"))
    )


def configure(
    project: str = "coding-agent",
    api_key: str | None = None,
    endpoint: str | None = None,
) -> None:
    """配置 LangSmith。

    不传 api_key 则从 LANGCHAIN_API_KEY 环境变量读取。
    """
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project
    if api_key:
        os.environ["LANGCHAIN_API_KEY"] = api_key
    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint


@contextmanager
def trace_run(
    name: str,
    run_type: str = "chain",
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> Iterator[dict]:
    """手动创建 trace 节点。

    用法:
        with trace_run("custom_step", metadata={"user": "x"}) as run:
            run["output"] = do_something()
    """
    run_info: dict = {
        "name": name,
        "run_type": run_type,
        "metadata": metadata or {},
        "tags": tags or [],
        "output": None,
    }

    if not is_enabled():
        yield run_info
        return

    try:
        from langsmith import trace
        with trace(
            name=name,
            run_type=run_type,
            metadata=metadata,
            tags=tags,
        ) as run:
            yield run_info
            if run_info["output"] is not None:
                run.end(outputs={"output": run_info["output"]})
    except ImportError:
        yield run_info


def status_text() -> str:
    """返回 tracing 状态描述。"""
    if not is_enabled():
        return "(未启用)"
    project = os.getenv("LANGCHAIN_PROJECT", "default")
    return f"已启用 (project={project})"