# scripts/eval_thinking_router.py
from middleware.thinking_router import ThinkingRouterConfig, classify_task

# 你人工标注的测试集
# (任务文本, 期望是否需要思考, 备注)
CASES = [
    # --- 应该关思考 ---
    ("读一下 README", False, "明确读指令"),
    ("看看 src/main.py", False, "查看指令"),
    ("列出所有 py 文件", False, "列出指令"),
    ("跑一下测试", False, "执行指令"),
    ("改一下 config.py 第 42 行", False, "单点修改"),
    # --- 应该开思考 ---
    ("为什么这个函数会返回 None", True, "因果推理"),
    ("帮我设计一个缓存层", True, "设计"),
    ("分析这个项目的模块结构", True, "分析 + 多文件"),
    ("优化这个查询的性能", True, "优化 + 推理"),
    ("诊断一下登录失败的原因", True, "诊断"),
    ("解释一下这个项目的架构和设计取舍", True, "架构 + 权衡"),
    # --- 边界情况（最难判） ---
    ("帮我看看这个报错", True, "看'看看'但实际需要诊断"),
    ("帮我修复登录问题", True, "修复通常需要诊断"),
    ("把这个函数重命名为 xxx", False, "机械操作"),
    ("加上 type hints", False, "机械操作"),
    ("这段代码能优化吗", True, "需要判断"),
    ("这个方案可行吗", True, "需要权衡"),
]

cfg = ThinkingRouterConfig()
correct = 0
total = len(CASES)
false_off = []  # 该思考但判了不思考
false_on = []  # 不该思考但判了思考

for text, expected, note in CASES:
    need, reason = classify_task(text, cfg)
    mark = "✓" if need == expected else "✗"
    print(f"{mark}  [{'ON ' if need else 'OFF'}]  {text}")
    print(f"     期望={'ON' if expected else 'OFF'} 理由={reason}  ({note})")
    print()
    if need == expected:
        correct += 1
    elif not need and expected:
        false_off.append((text, reason, note))
    else:
        false_on.append((text, reason, note))

print(f"\n准确率: {correct}/{total} = {correct / total:.1%}")
print(f"\n漏判（该思考但关了）: {len(false_off)}")
for t, r, n in false_off:
    print(f"  - {t!r}  ({r})")
print(f"\n误判（不该思考但开了）: {len(false_on)}")
for t, r, n in false_on:
    print(f"  - {t!r}  ({r})")
