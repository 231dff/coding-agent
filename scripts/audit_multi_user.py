"""多用户隔离审计工具。

用法：
    python scripts/audit_multi_user.py

输出：
    - 所有已知 user_id
    - 每个 user 的卡片数 / 摘要数 / 经验数
    - 检查数据是否真正隔离（namespace 前缀）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从项目根运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from memory.store import current_user_id, get_store, store_backend_info

    print("=" * 60)
    print("多用户隔离审计")
    print("=" * 60)
    print()

    info = store_backend_info()
    print(f"Store 后端:   {info.get('backend', '?')}")
    print(f"Store 类型:   {info.get('type', '?')}")
    print(f"当前 user_id: {current_user_id()}   ← 环境变量 AGENT_USER_ID")
    print()

    store = get_store()

    # ---------- 扫描所有 namespace ----------
    try:
        namespaces = store.list_namespaces()
    except Exception as e:
        print(f"list_namespaces 失败: {e}")
        return 1

    # 按 user_id 分组统计
    user_stats: dict[str, dict[str, int]] = {}

    for ns in namespaces:
        # ns 形如 ("users", "default", "cards", "active")
        if len(ns) < 3 or ns[0] != "users":
            continue
        uid = ns[1]
        kind = ns[2] if len(ns) > 2 else "?"

        user_stats.setdefault(uid, {"cards": 0, "summaries": 0, "other": 0})

        # 统计每个 namespace 里的条目数
        try:
            items = store.search(ns, limit=100000)
            n = len(items)
        except Exception:
            n = 0

        if kind == "cards":
            user_stats[uid]["cards"] += n
        elif kind == "summaries":
            user_stats[uid]["summaries"] += n
        else:
            user_stats[uid]["other"] += n

    # ---------- 输出 ----------
    if not user_stats:
        print("(没有任何用户数据)")
        print()
        print("提示：跑几个任务后才会产生数据。")
        return 0

    print(f"发现 {len(user_stats)} 个 user_id:")
    print()
    print(f"  {'user_id':<20}  {'cards':>8}  {'summaries':>11}  {'other':>8}")
    print(f"  {'-' * 20}  {'-' * 8}  {'-' * 11}  {'-' * 8}")

    for uid in sorted(user_stats.keys()):
        s = user_stats[uid]
        marker = " ← 当前" if uid == current_user_id() else ""
        print(f"  {uid:<20}  {s['cards']:>8}  {s['summaries']:>11}  {s['other']:>8}{marker}")

    print()

    # ---------- 隔离检查 ----------
    print("隔离检查:")
    if len(user_stats) == 1:
        print("  ✅ 只有一个 user，没有串数据的风险")
    else:
        print(f"  ⚠️  有 {len(user_stats)} 个 user——确认他们是独立的")
        print("     若所有数据都应是同一个人的，请检查 AGENT_USER_ID 环境变量")

    print()
    print("=" * 60)
    print("说明:")
    print("  - 数据按 namespace 前缀隔离：('users', user_id, ...)")
    print("  - 切换 user：AGENT_USER_ID=xxx coding-agent ...")
    print("  - 默认 user：'default'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
