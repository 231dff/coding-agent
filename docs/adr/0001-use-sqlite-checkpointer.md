# ADR-0001: 用 SQLite SqliteSaver 而非 InMemorySaver

- **状态**：已采纳
- **日期**：2026-09-18
- **决策者**：@231dff

## 背景

Coding Agent 需要在用户关闭进程后保留会话状态。原实现用 LangGraph 的
`InMemorySaver`，进程结束状态即丢——用户关掉 `coding-agent` 再打开，
之前的对话上下文全部丢失。

选项：
1. `InMemorySaver`（现状）— 快、零依赖、不持久
2. 手动读写 JSONL 轨迹
3. `SqliteSaver`（LangGraph 官方）
4. `PostgresSaver`（LangGraph 官方）

## 决策

采用 **`SqliteSaver`**，存储在：
<project>/.coding-agent/sessions/checkpoints.db


## 理由

- **LangGraph 原生**：不用自己写 message 序列化、反序列化
- **支持完整 state**：不只 messages，还有 tool_calls、interrupt 状态
- **零外部依赖**：SQLite 随 Python 附带
- **WAL 模式**：支持单写多读，与 `metrics.db` 模式一致
- **单文件**：便于备份、迁移、调试

`PostgresSaver` 虽然更适合多用户场景，但现阶段只有 CLI 使用，引入
Postgres 的运维成本不划算。

## 后果

### 正面
- 会话恢复工作正常，用户体感提升
- 崩溃后可恢复（轨迹文件 + checkpoints.db）
- 与 `--thread-id` 配合，支持多会话

### 负面
- 需要维护 `checkpoints.db`（清理、备份）
- 受 SQLite 单写限制（但对单用户 CLI 无影响）
- 数据库损坏时需要删文件重建（会丢会话）

### 迁移路径

如果未来做 Web 多用户，切换方案是：

