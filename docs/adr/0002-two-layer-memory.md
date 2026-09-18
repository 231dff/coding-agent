
---

## 2. `docs/adr/0002-two-layer-memory.md`（新建）

```markdown
# ADR-0002: 双层记忆架构

- **状态**：已采纳
- **日期**：2026-09-18
- **决策者**：@231dff

## 背景

Agent 需要跨会话记住用户偏好和工作经验。早期实现是一个
`user.md` Markdown 文件，全量注入 system prompt。

数据量增长后暴露三个问题：
1. **system prompt 膨胀**：100 条偏好 ~2000 token，还在增长
2. **检索精度下降**：所有记忆平铺，模型难以聚焦
3. **无法区分层次**：用户偏好（个人）和工程经验（可复用）混在一起

## 决策

采用**双层架构**：

### 第 1 层：Advanced JSON Cards（常驻上下文）

- 8 字段结构化卡片
- 全局存储：`~/.coding-agent/memory/user_cards.jsonl`
- 启动时全量注入 system prompt
- 按 `confidence` 排序，最多 40 条

### 第 2 层：上下文感知检索（按需拉取）

- 会话摘要存全局：`~/.coding-agent/knowledge/raw_sessions.jsonl`
- 向量索引：`~/.coding-agent/knowledge/chroma/`
- 运行时按当前任务检索 top-K
- 作为 `HumanMessage` 追加到消息末尾

## 理由

### 为什么不全用检索？

高频信息（"我喜欢 pytest"）每次检索都有延迟且可能漏召，
常驻更可靠。

### 为什么不全量注入？

长尾信息（"三个月前调试过某个缓存问题"）不常用，
全量注入浪费 token 且稀释注意力。

### 为什么卡片而非纯文本？

- **可追溯**：每条卡片带 `backstory` + `evidence`
- **可版本化**：`supersedes` 字段记录取代关系
- **可消歧**：`person` + `relationship` 区分"我的医生"和"父亲的医生"
- **可排序**：`confidence` 决定注入优先级

## 后果

### 正面
- system prompt 有上限（40 条卡片 ≈ 800 token）
- 检索层覆盖长尾
- 卡片可审计、可手工编辑

### 负面
- 会话结束需要 2 次 LLM 调用（提炼卡片 + 摘要）
- 需要维护两套存储（卡片 + 摘要 + 向量）
- 首次使用需要下载嵌入模型（~100MB，hybrid/chroma 模式）

### 缓解
- 提炼改为**异步**（见 ADR-0004）
- 向量模型延迟加载（见 `retriever.py` 的 `_ensure_initialized`）
- 默认 `AGENT_RETRIEVER=bm25`（零依赖）

## 参考

- 代码位置：`memory/cards.py`、`memory/card_extractor.py`、`memory/session_summary.py`、`memory/retriever.py`
- 书《深入理解 AI Agent》第 3 章