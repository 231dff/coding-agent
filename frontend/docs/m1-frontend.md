# M1-F 里程碑报告 — 脚手架与 SSE 打通

## 验收标准
- [x] `pnpm dev` 可启动，三栏布局可交互
- [x] 发送消息收到 SSE 事件流
- [x] 事件类型全覆盖：token / tool_start / tool_end / error / done
- [x] 中断功能可用
- [x] 单元测试 5 个 SSE 解析测试全通过
- [x] 冒烟测试 1 个 ChatPanel 端到端测试通过

## 已知限制
- 事件以 JSON 原始形式展示（Day 6-7 会转为可视化消息）
- 无会话管理（Day 21）
- 无审批（Day 16-20）
- 无产物面板（Day 11-15）