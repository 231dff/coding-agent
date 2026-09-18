# ADR-0004: 异步提炼 + pending 标记

- **状态**：已采纳
- **日期**：2026-09-18
- **决策者**：@231dff

## 背景

会话结束时需要做两件事：
1. 提炼用户卡片（LLM 调用，2-15 秒）
2. 生成会话摘要（LLM 调用，2-15 秒）

同步执行导致用户 `/exit` 后要等 4-30 秒才能回到 shell。
体验很差。

## 决策

**三步走**：

1. **写 pending 标记**（< 1ms）
<project>/.coding-agent/memory/pending.jsonl


2. **启动 daemon 线程异步提炼**

t = threading.Thread(target=_do_extraction, daemon=True)
t.start()
t.join(timeout=1.0)  

3. **下次启动时检查 pending，补跑未完成的**


process_pending_on_startup(rt, thread_id)