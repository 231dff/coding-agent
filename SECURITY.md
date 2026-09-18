---
AIGC:
    Label: "1"
    ContentProducer: 001191110102MACQD9K64018705
    ProduceID: 7642208309482733858-data_volume/files/所有对话/主对话/SECURITY.md
    ReservedCode1: ""
    ContentPropagator: 001191110102MACQD9K64028705
    PropagateID: 467726794233428#1789716912657
    ReservedCode2: ""
---
# 安全政策

## 支持的版本

| 版本 | 支持 |
| --- | --- |
| 0.1.x | ✅ 安全更新 |
| < 0.1 | ❌ |

## 报告漏洞

**不要开 public issue。** 请发邮件到 `security@example.com`，或使用 [GitHub 私密漏洞报告](https://github.com/231dff/coding-agent/security/advisories/new)。

**回复时间：**

- 24 小时内确认收到
- 72 小时内给出初步评估
- 7 天内给出修复计划（或说明为何不修复）

**报告内容建议：**

- 影响范围（哪些版本受影响）
- 复现步骤
- 最小 PoC（如果能提供）
- 是否已公开

**致谢：** 确认有效的漏洞会在修复后记入 `SECURITY-ACKNOWLEDGMENTS.md`（如你同意）。

## 威胁模型

### 1. 提示注入（Prompt Injection）

**风险**：攻击者在网页、文档、邮件、MCP 工具描述中嵌入指令，诱导 Agent 执行非预期操作。

**防护**：

- 输入侧：`ContentStripperMiddleware` 清洗输入中的可疑注入指令
- 上下文侧：外部内容用边界标记包裹并注明来源
- 执行侧：敏感工具（`shell_exec`、`write_file`）需人工审批
- 沙箱侧：默认断网，防数据外泄

**限制**：

- 无法完全防止**间接注入**（比如攻击者在 GitHub issue 中隐藏指令）
- 对**多步骤社交工程**（诱导 Agent 一步步走向危险操作）防护有限

### 2. 敏感信息泄露

**风险**：

- API Key 被写入日志
- 用户凭证被上传到 LLM Provider
- 沙箱内读取宿主机敏感文件

**防护**：

- `observability/redact.py` 自动脱敏日志中的 key / token / password
- 凭证文件不挂载进沙箱
- API Key 存在 `~/.coding-agent/credentials.yaml`，而非代码内

**限制**：

- 用户如果自己把密钥写进 prompt，Agent 会原样发给 LLM
- 脱敏仅对结构化字段生效，对**自由文本**中的密钥无效

### 3. 越权操作

**风险**：

- Agent 修改项目外的文件
- Agent 删除系统关键文件
- Agent 执行破坏性命令（`rm -rf /`）

**防护**：

- 文件工具用 `_resolve()` 阻止 `../` 路径逃逸
- 沙箱内限制可访问路径
- 危险命令做语义解析（不只看关键字黑名单）
- `IdempotencyMiddleware` 防止重复执行

**限制**：

- 沙箱逃逸（Docker 内核漏洞）
- 通过合法工具实现破坏（如先 `read` 再 `edit` 删除内容）

### 4. 供应链攻击

**风险**：

- 依赖包被投毒
- MCP 服务器被劫持
- Skill 定义中嵌入恶意指令

**防护**：

- CI 集成 `pip-audit` 检查 CVE
- MCP 工具描述人工审查
- Skill 定义放在 git 里，改动可见

**限制**：

- 无法防 **0-day** 或**社会工程**（比如你信任了一个恶意的上游作者）
- MCP 服务器可随时更改工具行为

## 已知限制

### 沙箱

- 依赖 Docker，**内核漏洞未隔离**
- 默认断网，但可配置白名单
- 使用 `no-new-privileges` + `cap_drop=ALL`，但不能防所有攻击

### 凭证管理

- `~/.coding-agent/credentials.yaml` **明文存储**
- 建议用环境变量替代（`OPENAI_API_KEY` 等）
- 文件权限建议：`chmod 600 ~/.coding-agent/credentials.yaml`

### 工具审批

- 敏感工具需人工审批（可配置）
- 默认敏感工具：`shell_exec`、`write_file`、`edit_file`、`git_push`
- **审批可被绕过**：如果用户手动把敏感工具从列表移除

### 记忆系统

- 卡片、摘要存在 `~/.coding-agent/`，**未加密**
- 用户偏好可能包含敏感信息（如“我在 XX 公司工作”）
- 多用户场景需用 Postgres 后端 + user_id 隔离

### LLM 调用

- 上下文完整发给 Provider，**Provider 会看到你的代码**
- 部分 Provider 有数据保留政策，请查看其隐私条款
- 敏感项目建议用本地模型（Ollama）或私有部署

## 安全建议

### 1. 最小权限

- **只在必要的项目目录运行**，不要在主目录（`~`）跑
- 用 `--project /path/to/project` 明确指定
- 不要在包含 SSH key、数据库密码的目录运行

### 2. 环境隔离

- **生产环境用 Docker 部署**
- 沙箱和主进程分离
- 用只读挂载保护代码目录（工作区除外）

### 3. 凭证管理

优先用环境变量，而不是配置文件：

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

```bash
# Linux / macOS
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

如果使用凭证文件，请收紧权限：

```bash
chmod 600 ~/.coding-agent/credentials.yaml
```

### 4. 审计日志

```bash
# 开启 JSON 格式日志，便于审计
export LOG_JSON=true
```

```powershell
# Windows：在日志中搜索 trace_id，追踪完整调用链
Select-String -Path logs\*.log -Pattern "trace_id="
```

### 5. 依赖审计

```bash
# 定期运行 pip-audit（CI 已集成，关注 Actions 告警）
pip-audit
```

### 6. 人工审批

```yaml
# ~/.coding-agent/config.yaml
approval:
  enabled: true
  sensitive_tools:
    - shell_exec
    - write_file
    - git_push
    - process_refund
```

## 安全更新

### 自动更新（推荐）

```bash
# 定期更新到最新版本
pip install -e ".[dev]" --upgrade
```

关注 [GitHub Releases](https://github.com/231dff/coding-agent/releases) 获取安全公告。

### 手动检查

```bash
# 查看当前版本
coding-agent --version

# 查看可用的最新版本
pip index versions coding-agent
```

## 漏洞分类

| 等级 | 例子 | 响应时间 |
| --- | --- | --- |
| Critical | 远程代码执行、任意文件读写 | 24 小时内 |
| High | 提示注入导致数据外泄、沙箱逃逸 | 72 小时内 |
| Medium | 敏感信息泄露到日志、越权访问 | 7 天内 |
| Low | DoS、信息暴露（非敏感） | 30 天内 |

## 参考

- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/)
- LangChain 安全指南
- Docker 安全最佳实践

---


