"""逐个检查 agent.core 及其依赖链的模块是否可导入。

用法：
    uv run python scripts/check_imports.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# 添加项目根到 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# agent/core.py 直接 import 的模块
DIRECT_IMPORTS = [
    "agent.config",
    "sandbox.docker_backend",
    "sandbox.patch",
    "tools.registry",
    "tools.sandbox_ops",
    "tools.transaction_ops",
    "tools.context_ops",
    "tools.test_ops",
    "codebase.parser",
    "codebase.dep_graph",
    "codebase.call_graph",
    "codebase.impact",
    "codebase.repo_map",
    "codebase.indexer",
    "codebase.background_indexer",
    "middleware.dependency_check",
    "middleware.prompt_cache",
    "middleware.context_compaction",
    "middleware.tool_filter",
    "middleware.tool_search",
    "context.assembly",
    "skills.registry",
    "skills.loader",
    "agent.graph",
    "agent.test_loop",
    "mcp.client",
]

# 间接依赖（被上面模块 import，但 core 本身不直接引用）
INDIRECT_IMPORTS = [
    "sandbox.base",
    "sandbox.shell",
    "sandbox.transaction",
    "context.budget",
    "context.noise_filter",
    "context.api_compaction",
    "context.summarize",
    "context.full_compaction",
    "context.offload",
    "memory.store",
    "memory.project_memory",
    "memory.session_memory",
    "memory.tools",
    "observability.tracing",
    "observability.metrics",
    "observability.cost",
    "observability.logger",
]

# 第三方依赖
THIRD_PARTY = [
    "langchain",
    "langgraph",
    "pydantic",
    "tree_sitter",
    "tree_sitter_python",
    "networkx",
    "chromadb",
    "docker",
    "tiktoken",
    "structlog",
    "fastapi",
    "uvicorn",
    "langchain_mcp_adapters",
    "mcp",
]


def check(module_name: str) -> tuple[bool, str]:
    """返回 (是否成功, 错误信息)。"""
    try:
        importlib.import_module(module_name)
        return True, ""
    except ModuleNotFoundError as e:
        # 提取缺失的顶层模块名
        missing = str(e).split("'")[1] if "'" in str(e) else str(e)
        return False, f"缺少依赖: {missing}"
    except ImportError as e:
        return False, f"导入错误: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    print("=" * 70)
    print("检查第三方依赖")
    print("=" * 70)
    for mod in THIRD_PARTY:
        ok, err = check(mod)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {mod:30s} {err}")

    print()
    print("=" * 70)
    print("检查 agent.core 直接依赖")
    print("=" * 70)
    direct_fail = []
    for mod in DIRECT_IMPORTS:
        ok, err = check(mod)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {mod:40s} {err}")
        if not ok:
            direct_fail.append((mod, err))

    print()
    print("=" * 70)
    print("检查间接依赖")
    print("=" * 70)
    indirect_fail = []
    for mod in INDIRECT_IMPORTS:
        ok, err = check(mod)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {mod:40s} {err}")
        if not ok:
            indirect_fail.append((mod, err))

    # 最后尝试导入 agent.core
    print()
    print("=" * 70)
    print("尝试导入 agent.core")
    print("=" * 70)
    ok, err = check("agent.core")
    if ok:
        print("  ✓ agent.core 可导入")
    else:
        print("  ✗ agent.core 导入失败")
        print(f"    {err}")

    # 汇总
    all_fail = direct_fail + indirect_fail
    print()
    print("=" * 70)
    if not all_fail and ok:
        print(f"✓ 全部通过（{len(DIRECT_IMPORTS) + len(INDIRECT_IMPORTS)} 个模块）")
        return 0
    else:
        print(f"✗ {len(all_fail)} 个模块缺失或失败")
        for mod, err in all_fail:
            print(f"    - {mod}: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
