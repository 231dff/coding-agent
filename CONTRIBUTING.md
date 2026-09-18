---
AIGC:
    Label: "1"
    ContentProducer: 001191110102MACQD9K64018705
    ProduceID: 7642208309482733858-data_volume/files/所有对话/主对话/CONTRIBUTING.md
    ReservedCode1: ""
    ContentPropagator: 001191110102MACQD9K64028705
    PropagateID: 467726794233428#1789716590160
    ReservedCode2: ""
---
# 贡献指南

欢迎参与！本文档说明如何搭建环境、提 PR、报告问题。

## 目录

- [一、开发环境](#一开发环境)
- [二、代码风格](#二代码风格)
- [三、测试](#三测试)
- [四、提交规范](#四提交规范)
- [五、代码审查](#五代码审查)
- [六、报告问题](#六报告问题)
- [七、目录导航](#七目录导航)
- [八、常见问题](#八常见问题)
- [九、License](#九license)
- [十、联系方式](#十联系方式)

---

## 一、开发环境

### 前置要求

- Python 3.11+
- Docker Engine（沙箱功能需要）
- Git
- （可选）Node.js 20+ 与 pnpm（Web 界面）

### 安装

```bash
# 1. Fork 并克隆
git clone https://github.com/<your-username>/coding-agent.git
cd coding-agent

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 配置模型（首次运行）
coding-agent init

# 5. 验证
pytest tests/ -v
```

### Windows 用户注意

请设置 UTF-8 模式，否则中文测试会失败：

```powershell
$env:PYTHONUTF8 = "1"
```

建议写进 PowerShell profile，一劳永逸：

```powershell
# 编辑 profile
notepad $PROFILE

# 加一行
$env:PYTHONUTF8 = "1"
```

---

## 二、代码风格

提交前必须通过：

```bash
ruff check .
ruff format --check .
```

自动修复：

```bash
ruff check . --fix
ruff format .
```

### 风格约定

- 行宽 100
- 使用双引号
- import 分组：`__future__` → 标准库 → 第三方 → 本地
- 类型注解：新代码必须有
- docstring：公开函数必须有

### 请不要

- 用 `print` 调试（请用 `logger`）
- 硬编码密钥（请用环境变量）
- 提交 `.venv/` 或 `.coding-agent/`
- 提交 `*.bak` 文件

---

## 三、测试

新功能必须带测试，覆盖率不能下降。

### 常用命令

```bash
# 全部测试
pytest

# 带覆盖率（CI 门槛 70%）
pytest --cov=agent --cov=tools --cov=context \
  --cov-report=term-missing \
  --cov-fail-under=70

# 单个模块
pytest tests/test_memory.py -v

# 排除慢测试
pytest -m "not slow"

# 查看跳过的测试原因
pytest -rs
```

### 测试约定

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 单元测试 | `tests/test_xxx.py` | 主测试 |
| 契约测试 | `tests/contracts/test_xxx.py` | 防 schema 漂移 |
| 集成测试 | `tests/integration/` | 需要 Docker / 网络 |

命名：`test_<被测函数>_<场景>`

### 测试原则

- 不依赖外部服务（mock 掉 LLM / Docker / 网络）
- 用 `tmp_path` 而非全局路径
- 一个测试只测一件事
- 断言要具体，不要只写 `assert result`

---

## 四、提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

| 前缀 | 用途 | 示例 |
| --- | --- | --- |
| `feat:` | 新功能 | `feat: add hybrid retrieval` |
| `fix:` | bug 修复 | `fix: sandbox no longer deletes files` |
| `docs:` | 文档 | `docs: add ADR-0001` |
| `refactor:` | 重构（不改行为） | `refactor: extract card store` |
| `test:` | 测试 | `test: add pool safety regression` |
| `chore:` | 构建/依赖/工具 | `chore: bump ruff to 0.7` |
| `perf:` | 性能优化 | `perf: parallel sandbox + codebase` |

### 规则

- 一个 PR 只做一件事（避免一次改 5 个不相关的文件）
- 描述清楚 **why**，不只写 what
- 大改动先开 issue 讨论

### 提交信息示例

```text
feat: add two-layer memory architecture

- Layer 1: Advanced JSON Cards (8 fields, global storage)
- Layer 2: session summary + retrieval (hybrid RRF)
- Async extraction with pending marker

Closes #42
```

---

## 五、代码审查

### 审查流程

1. 提交 PR → 自动跑 CI
2. CI 全绿 → 请求 review
3. 至少一人 approve → 合并

### CI 门槛

- `ruff check .` 通过
- `ruff format --check .` 通过
- `pytest` 通过
- 覆盖率 ≥ 70%
- 双平台（Ubuntu + Windows）通过

### 审查重点

- 逻辑正确性 > 代码风格
- 边界情况是否处理
- 是否有测试覆盖
- 是否更新文档
- 是否有安全隐患（密钥、注入、越权）

### 关键模块（需两人审查）

- `agent/core.py`（装配逻辑）
- `memory/`（数据持久化）
- `sandbox/`（安全关键）
- `.github/workflows/`（CI 配置）

---

## 六、报告问题

### Bug 报告

请使用 [Bug 报告模板](.github/ISSUE_TEMPLATE/bug_report.md)，并附上：

- 环境（OS、Python 版本、`coding-agent` 版本）
- 复现步骤
- 期望行为 vs 实际行为
- `trace_id` + 相关日志

如何获取 `trace_id`：

```powershell
# CLI 启动时会显示
coding-agent
# trace_id: 9f8e7d6c5b4a

# 从日志里搜索
Select-String -Path logs\*.log -Pattern "trace_id=9f8e7d6c5b4a"
```

### 功能建议

请使用 [功能建议模板](.github/ISSUE_TEMPLATE/feature_request.md)。

---

## 七、目录导航

| 目录 | 说明 |
| --- | --- |
| `agent/` | Agent 核心 |
| `codebase/` | 代码库理解 |
| `context/` | 上下文管理 |
| `sandbox/` | 沙箱（安全关键） |
| `tools/` | 37 个工具 |
| `middleware/` | 11 个中间件 |
| `memory/` | 双层记忆 |
| `skills/` | 55 个技能 |
| `mcp_client/` | MCP 集成 |
| `observability/` | 日志 / 指标 / 追踪 |
| `api/` | FastAPI 网关 |
| `frontend/` | React Web 界面 |
| `tests/` | 测试 |
| `docs/` | 文档（含 ADR） |

---

## 八、常见问题

### Q：测试报 `UnicodeEncodeError: 'charmap'`？

Windows 编码问题。请设置：

```powershell
$env:PYTHONUTF8 = "1"
```

### Q：Docker 测试全部 skip？

正常。Windows 和 CI 上默认 skip。本地想跑需要：

- Linux / macOS，或 Windows + Docker Desktop + WSL2

### Q：`pip-compile` 报 SSL 错误？

使用国内镜像源：

```powershell
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
```

### Q：修改了系统提示词，如何验证？

```bash
pytest tests/ -v
python -m evals --baseline evals/baseline.json
```

---

## 九、License

MIT。提交即表示你同意以 MIT 协议发布你的贡献。

---

## 十、联系方式

- Issue：<https://github.com/231dff/coding-agent/issues>
- 讨论：<https://github.com/231dff/coding-agent/discussions>

---

。
