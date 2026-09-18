<div align="center">

# 🤖 Coding Agent

**对任意项目进行代码理解、修改与测试的自主编码智能体**

*Read it. Change it. Test it. Fix it. — 全部自动化。*

[![CI](https://github.com/231dff/coding-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/231dff/coding-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-219%20collected-success)](tests/)
[![Tools](https://img.shields.io/badge/tools-37-blue)](tools/)
[![Skills](https://img.shields.io/badge/skills-55-blueviolet)](skills/)

[快速开始](#-快速开始) ·
[核心特性](#-核心特性) ·
[架构总览](#-架构总览) ·
[使用示例](#-使用示例) ·
[配置](#-配置) ·
[测试](#-测试)

</div>

---

## ✨ 这是什么

**Coding Agent** 是一个基于 **LangChain + LangGraph** 的生产级代码编辑智能体。它不像普通的 Chatbot 只会"说"，而是真的能**读代码、改文件、跑测试、修 bug**——完成整个工程闭环。

它有 **CLI** 与 **Web** 两种交互方式，10+ 模型 Provider 可选，内置隔离的 Docker 沙箱与 55 个领域技能。

```python
$ coding-agent "给 calc.py 的 add 函数补 docstring 并加单元测试"

💭 读取 calc.py
   ⚙ read_file ✓
💭 检查是否已有测试文件
   ⚙ glob_files ✓
💭 补 docstring
   ⚙ edit_file ✓
💭 新建测试
   ⚙ write_file ✓
💭 跑测试验证
   ⚙ run_tests ✓

✅ 完成：补了 docstring，新增 3 个单元测试，全部通过（3 passed in 0.42s）
```

---

## 🎯 核心特性

### 🧠 代码理解

- **Tree-sitter** 解析 → 依赖图 / 调用图 / 影响分析
- **仓库地图**（repo map）+ **语义检索** + **符号定位**
- 修改前自动分析**调用方影响范围**

### 🔒 安全执行

- **Docker 沙箱**隔离（内存 / CPU 限制、默认断网）
- **事务式多文件修改**：要么全成功，要么全回滚
- 敏感操作**人工审批**

### 🔄 自主循环

- **规划图**（planning graph）→ 拆解任务
- **修复图**（repair graph）→ 改-测-修闭环
- **条件化思考** → 简单任务关思考（快 4 倍），复杂任务开思考

### 🌐 多模型

- 通义千问 / OpenAI / Claude / DeepSeek / Kimi / 智谱 / Gemini / OpenRouter / Ollama / 自定义
- 统一 OpenAI 兼容接口 + Anthropic 原生接口

### 🛠️ 工具与技能

- **37 个内置工具**：文件、沙箱、事务、代码库、测试、状态、子 Agent（另有 MCP 动态工具）
- **55 个技能**（33 模型可见 + 22 内部子文档）：TDD / 代码评审 / 领域建模 / 排查 bug…
- **MCP 协议**接入 Git / Web 搜索 / DB 等外部工具

### 📊 可观测性

- **结构化日志**、**成本统计**、**指标存储**
- **LangSmith 追踪** + **轨迹回放**
- **评测框架**（evals）：任务集 + 基线对比 + 回归门禁

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        接入层                                │
│   CLI (agent/main.py)  ·  FastAPI 网关 (api/server.py)       │
│   React Web 界面 (frontend/)                                 │
├─────────────────────────────────────────────────────────────┤
│                      Agent 装配 (agent/core.py)              │
│   系统提示 · 工具集 · 中间件链 · 规划图 · 修复图              │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  代码理解     │   沙箱执行    │   中间件      │   可观测性     │
│  codebase/   │   sandbox/   │  middleware/ │ observability/ │
│  (依赖/调用图,│  (Docker隔离, │  (熔断/压缩/ │  (日志/成本/   │
│   索引/检索)  │   事务/补丁)  │   指标/缓存)  │   指标/追踪)   │
├──────────────┴──────────────┴──────────────┴────────────────┤
│  工具层 tools/ · 技能 skills/ · MCP mcp_client/ · 上下文 context/ │
└─────────────────────────────────────────────────────────────┘
```

**执行流程**

```
用户输入
   ↓
上下文装配（系统提示 + 项目记忆 + 技能元数据 + 状态栏）
   ↓
中间件链（思考路由 → 压缩 → 过滤 → 指标 → 安全 → 缓存）
   ↓
LLM 决策 → 工具调用 → 沙箱 / 代码库 / 事务执行
   ↓
结果回流 → 循环，直到任务完成
```

---

## 🚀 快速开始

### 前置要求

| 项 | 说明 |
|---|---|
| **Python 3.11+** | 必需 |
| **Docker Engine** | 沙箱执行需要（不装也能跑，只是跳过沙箱测试） |
| **模型 API Key** | 千问 / OpenAI / Anthropic / DeepSeek 等**任选一个** |
| Node.js 20+ | 仅 Web 界面需要 |

### 三步上手

```bash
# 1. 克隆并安装
git clone https://github.com/231dff/coding-agent.git
cd coding-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. 配置模型（首次运行自动进入向导）
coding-agent init

# 3. 开始使用
cd /path/to/your/project
coding-agent "解释这个项目的模块结构"
```

### Web 界面（可选）

```bash
# 后端（默认 mock 模式，无需真实模型）
python -m api.server

# 前端
cd frontend
pnpm install && pnpm dev          # → http://localhost:5173
```

### Docker 一键部署

```bash
# 构建沙箱镜像
docker build -t coding-agent-sandbox:latest docker/

# 启动完整服务（Agent + Postgres）
cd deploy
cp .env.example .env              # 编辑填入 API Key
docker compose up -d
```

---

## 💡 使用示例

### CLI 单次任务

```bash
coding-agent "把 src/utils.py 里所有 print 改成 logger.info"
coding-agent "为什么 add 函数返回 None？"
coding-agent "给 src/api/ 下所有文件补 type hints"
```

### 交互模式

```bash
$ coding-agent

你 /help
你 读一下 README
你 帮我在 calc.py 加 subtract 函数并写测试
你 /skills
你 /metrics
你 /exit
```

**交互命令一览**

| 命令 | 作用 |
|---|---|
| `/exit` `/quit` | 退出 |
| `/help` | 帮助 |
| `/clear` | 清空会话状态 |
| `/skills` | 列出所有技能 |
| `/config` | 显示当前配置 |
| `/metrics` | 会话指标（token / 成本 / 耗时） |
| `/trace` | 最近的 LLM 调用追踪 |
| `/<skill-name>` | 手动加载技能 |

### 条件化思考（默认开启）

```bash
$ coding-agent "读一下 README"                    # → 4.2s · 关闭思考
$ coding-agent "为什么这个函数返回 None"           # → 15s  · 开启思考
```

简单任务自动跳过 thinking，复杂任务保留。**简单任务延迟降低 60%+**。

---

## ⚙️ 配置

配置分层加载，优先级从高到低：

```
1. <project>/.coding-agent/config.yaml      # 项目级
2. ~/.coding-agent/config.yaml              # 全局
3. ~/.coding-agent/credentials.yaml         # API Key
4. 环境变量 AGENT_* / DASHSCOPE_API_KEY      # env
5. .env                                     # 兼容旧配置
```

**常用环境变量**

| 变量 | 说明 |
|---|---|
| `AGENT_MODEL` | 模型（如 `qwen:qwen-max`） |
| `AGENT_THINKING_ROUTER` | `true` / `false`，启用条件化思考 |
| `AGENT_THINKING_STRATEGY` | `auto` / `always` / `never` |
| `AGENT_COMPACTION_MODEL` | 压缩用的轻量模型 |
| `OPENAI_API_KEY` | OpenAI 兼容接口 Key |
| `ANTHROPIC_API_KEY` | Anthropic 原生接口 Key |
| `LANGCHAIN_TRACING_V2` | 开启 LangSmith 追踪 |

---

## 📁 项目结构

```
coding-agent/
├── agent/               # Agent 核心：入口、装配、配置、Provider、规划/修复图
├── codebase/            # 代码理解：解析器、依赖图、调用图、影响分析、索引、检索
├── context/             # 上下文管理：装配、预算、噪声过滤、压缩、外置存储
├── sandbox/             # 沙箱抽象 + Docker 后端、事务、补丁、错误分类
├── tools/               # 37 个内置工具：文件 / 沙箱 / 事务 / 代码库 / 测试 / 子 Agent
├── middleware/          # 中间件：思考路由、压缩、熔断、过滤、缓存、指标、轨迹
├── memory/              # 项目记忆与会话记忆
├── skills/              # 技能系统：注册表 + 55 个技能定义
├── mcp_client/          # MCP 客户端 + Git / Web 搜索 / DB 服务器
├── observability/       # 日志 / 成本 / 指标 / 追踪 / 轨迹写入
├── api/                 # FastAPI 网关：认证、审批、SSE、文件、指标
├── frontend/            # React 19 Web 界面
├── evals/               # 评测框架：数据集、运行器、评分器、报告
├── benchmarks/          # 基准测试：任务集 + 运行器
├── perf/                # 性能调优：缓存调参、优化器、剖析器
├── prompts/             # 系统提示词
├── queries/             # Tree-sitter 查询定义（python_tags.scm）
├── scripts/             # 开发辅助脚本（import skills、检查 imports 等）
├── docs/                # 文档与架构决策记录（ADR）
├── deploy/              # Docker 一键部署（docker-compose + healthcheck）
├── docker/              # 沙箱镜像 Dockerfile
├── tests/               # pytest 测试套件（219 个，含 contracts/integration/scenarios）
└── pyproject.toml       # 项目配置（依赖、ruff、pytest）
```

---

## 🧪 测试与评测

### 单元测试

```bash
# 全部
pytest

# 排除需要 Docker / 网络的测试
pytest -m "not integration"

# 带覆盖率
pytest --cov

# 看跳过的测试原因
pytest -rs
```

**当前状态**：`211 passed, 5 skipped, 3 integration deselected`（共 219 个用例；Linux + Windows 双平台 CI 全绿）

### 端到端评测

```bash
# 跑默认评测集
python -m evals --model qwen:qwen-max

# 并行
python -m evals --parallel --max-workers 4

# 与基线对比，触发回归门禁
python -m evals --baseline evals/baseline.json
```

评测任务定义在 `evals/tasks/`，涵盖单文件修改、多文件修改、bug 修复、依赖升级。

---

## 🧰 技术栈

**后端**

```
Python 3.11 · LangChain · LangGraph · FastAPI · Pydantic v2
Tree-sitter · NetworkX · ChromaDB · Docker SDK · MCP · Structlog
```

**前端**

```
React 19 · TypeScript · Vite · Tailwind CSS v4
Zustand · TanStack Query · CodeMirror · Recharts · i18next
```

**工程化**

```
pytest · ruff · mypy · GitHub Actions (Ubuntu + Windows)
```

---

## 🤝 贡献

欢迎 PR / Issue。

- 提交前请确保：
  ```bash
  ruff check . && ruff format --check . && pytest
  ```
- 遵循现有的目录结构与命名约定
- 新功能请附带单元测试

---

## 📄 License

[MIT](LICENSE) © 2026

---

<div align="center">

**⭐ 如果这个项目对你有帮助，欢迎 Star。**

*Built with ❤️ and a lot of ☕*

</div>