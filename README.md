# Coding Agent

> 对任意项目进行代码理解、修改与测试的自主编码智能体。

Coding Agent 是一个基于 **LangChain + LangGraph** 的生产级代码编辑智能体，同时提供**命令行（CLI）**与 **Web 界面**两种交互方式。它能够：

- 读懂任意项目的代码结构（依赖图、调用图、符号索引）
- 在隔离的 **Docker 沙箱**中安全地执行命令、运行测试
- 通过丰富的工具集自主完成「读代码 → 改代码 → 跑测试 → 修复」的完整闭环
- 支持**多模型 Provider**（通义千问 / OpenAI / Claude / DeepSeek / Kimi / 智谱 / Gemini / OpenRouter / Ollama / 自定义）
- 内置 **Skill 技能系统**、**MCP 工具接入**、**人工审批**、**可观测性指标**与**评测（Evals）框架**

---

## 目录

- [核心特性](#核心特性)
- [架构总览](#架构总览)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
  - [前置要求](#前置要求)
  - [本地安装（CLI）](#本地安装cli)
  - [Web 界面（可选）](#web-界面可选)
- [使用方式](#使用方式)
  - [CLI 命令行](#cli-命令行)
  - [配置](#配置)
- [评测（Evals）](#评测evals)
- [测试](#测试)
- [Docker 部署](#docker-部署)
- [技术栈](#技术栈)

---

## 核心特性

| 分类 | 能力 |
|------|------|
| **代码理解** | Tree-sitter 解析 → 依赖图 / 调用图 / 影响分析 / 仓库地图 / 语义检索 |
| **安全执行** | Docker 沙箱隔离（内存 / CPU 限制、默认断网），事务式多文件修改 |
| **自主循环** | 规划图（planning graph）+ 修复图（repair graph），「改-测-修」闭环 |
| **多模型** | 10+ Provider，统一 OpenAI 兼容 / Anthropic 原生接口，temperature 可选 |
| **上下文管理** | 上下文装配、预算控制、噪声过滤、感知式压缩、外置存储 |
| **中间件链** | 熔断器、依赖检查、工具过滤、工具搜索、提示缓存、轨迹持久化、指标采集 |
| **Skill 系统** | 可加载的技能定义（TDD / 代码评审 / 领域建模 / 排查 bug 等 40+ 技能） |
| **MCP 集成** | 通过 MCP 协议接入 Git / Web 搜索等外部工具 |
| **Web 界面** | React 19 前端：会话管理、流式对话、审批流、仪表盘、多语言、主题切换 |
| **安全与权限** | 角色权限（admin / developer / viewer）、OIDC / mock 认证、敏感工具人工审批 |
| **可观测性** | 结构化日志、成本统计、指标存储、LangSmith 追踪、轨迹回放 |
| **评测** | 内置评测任务集与回归门禁，支持并行执行、基线对比 |

---

## 架构总览

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
│  工具层 tools/  · 技能 skills/  · MCP mcp_client/ · 上下文 context/ │
└─────────────────────────────────────────────────────────────┘
```

**核心流程**：用户输入任务 → 系统提示 + 项目记忆 + 技能元数据装配上下文 → 中间件链预处理 → LLM 选择工具 → 工具在沙箱 / 代码库 / 事务层执行 → 结果回流，循环直至完成。

---

## 项目结构

```
coding agent/
├── agent/               # Agent 核心：入口、装配、配置、Provider、规划/修复图
├── codebase/            # 代码库理解：解析器、依赖图、调用图、影响分析、索引、检索
├── context/             # 上下文管理：装配、预算、噪声过滤、压缩、外置存储
├── sandbox/             # 沙箱抽象 + Docker 后端、事务、补丁、错误分类
├── tools/               # 工具集：文件/沙箱/事务/上下文/测试/状态/子 Agent/代码库
├── middleware/          # 中间件：熔断、依赖检查、工具过滤、压缩、指标、缓存、轨迹
├── memory/              # 记忆：项目记忆、会话记忆、存储、记忆工具
├── skills/              # 技能系统：注册表、加载器 + 40+ 技能定义
├── mcp_client/          # MCP 客户端 + Git / Web 搜索 / DB 服务器
├── observability/       # 可观测性：日志、成本、指标、存储、追踪、轨迹写入
├── api/                 # FastAPI 网关：认证、审批、会话、SSE、文件、指标
├── frontend/            # React 19 Web 界面（Vite + TS + Tailwind + Zustand）
├── evals/               # 评测框架：数据集、运行器、评分器、报告 + 任务定义
├── perf/                # 性能：缓存调优、优化器、剖析器
├── prompts/             # 系统提示词与工具模板
├── queries/             # Tree-sitter 查询（python_tags.scm）
├── deploy/              # 部署：Dockerfile、docker-compose、健康检查、环境变量样例
├── docker/              # 沙箱镜像 Dockerfile
├── tests/               # pytest 测试套件
├── docs/                # 文档
├── scripts/             # 辅助脚本
├── pyproject.toml       # Python 项目配置（依赖、构建、ruff/mypy/pytest）
└── requirements.txt     # 后端依赖（pip 安装方式）
```

---

## 快速开始

### 前置要求

- **Python 3.11+**
- **Docker Engine**（沙箱执行与容器部署需要）
- 至少一个模型 API Key（千问 / OpenAI / Anthropic / DeepSeek 等任意一个）
- （可选）**Node.js 20+ 与 pnpm** —— 仅使用 Web 界面时需要

### 本地安装（CLI）

```bash
# 1. 克隆仓库
git clone https://github.com/231dff/coding-agent.git
cd coding-agent

# 2. 安装依赖（推荐 uv）
uv venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# 或使用 pip
pip install -e ".[dev]"

# 3. 配置模型（首次运行会自动进入向导，也可手动初始化）
coding-agent init

# 4. 运行
coding-agent "给 calc.py 的 add 函数添加 docstring"
```

> 首次运行 `coding-agent init` 会引导你选择 Provider、填写 API Key、指定默认模型，配置会写入 `~/.coding-agent/` 与目标项目的 `.coding-agent/`。

### Web 界面（可选）

Web 界面由 FastAPI 后端 + React 前端组成：

```bash
# 1. 启动后端（默认 mock 模式，无需真实模型）
python -m api.server
#    AGENT_MODE=real python -m api.server   # 接入真实 Agent

# 2. 启动前端
cd frontend
pnpm install
pnpm dev          # http://localhost:5173
```

前端开发服务器会将 `/api` 代理到后端。默认认证模式为 `mock`（无需登录），生产环境请参考 [`deploy/.env.auth.example`](deploy/.env.auth.example) 配置 OIDC。

---

## 使用方式

### CLI 命令行

```bash
coding-agent init [--project PATH]            # 初始化配置向导
coding-agent [--project PATH] [--model MODEL] [task]   # 交互式或单次任务
```

进入交互模式后支持以下命令：

| 命令 | 说明 |
|------|------|
| `/exit` / `/quit` | 退出 |
| `/help` | 显示帮助 |
| `/clear` | 清空当前会话状态 |
| `/skills` | 列出所有技能 |
| `/config` | 显示当前配置 |
| `/metrics` | 显示本次会话指标 |
| `/trace` | 查看最近的调用指标 |
| `/<skill-name>` | 手动加载某个技能 |

### 配置

配置按优先级从高到低分层加载：

1. 项目级 `<project>/.coding-agent/config.yaml`
2. 全局 `~/.coding-agent/config.yaml`
3. API Key `~/.coding-agent/credentials.yaml`
4. 环境变量 `AGENT_*` / `DASHSCOPE_API_KEY` 等
5. `.env`（兼容旧配置）

支持的环境变量（示例见 [`.env.example`](.env.example)）：

| 变量 | 说明 |
|------|------|
| `AGENT_MODEL` | 模型选择，支持 `openai:` / `anthropic:` 前缀 |
| `AGENT_WORKSPACE` | 工作区路径 |
| `OPENAI_API_KEY` | OpenAI 兼容接口的 Key（千问等也走这个） |
| `OPENAI_BASE_URL` | OpenAI 兼容端点 |
| `ANTHROPIC_API_KEY` | Anthropic 原生接口 Key |
| `AGENT_MODEL_WINDOW` | 模型上下文窗口大小 |
| `LANGCHAIN_TRACING_V2` | 是否开启 LangSmith 追踪 |

---

## 评测（Evals）

项目内置评测框架，用于衡量 Agent 的代码编辑能力：

```bash
python -m evals --model openai:gpt-5.5
python -m evals --parallel --max-workers 4
python -m evals --baseline evals/baseline.json   # 与基线对比，触发回归门禁
```

评测任务定义在 [`evals/tasks/`](evals/tasks/) 下，涵盖单文件修改、多文件修改、bug 修复、依赖升级等场景。

---

## 测试

```bash
# 运行全部测试
pytest

# 排除需要外部依赖的测试
pytest -m "not integration"

# 带覆盖率
pytest --cov
```

测试套件覆盖：Agent 装配冒烟、上下文装配/预算/压缩、依赖图/调用图/仓库地图、Docker 沙箱后端、事务/补丁、MCP、技能系统、工具过滤等模块。

---

## Docker 部署

项目提供两种 Dockerfile：

- **`deploy/`** —— Agent 主进程部署（含 docker-compose，可挂载工作区、接入 Postgres 长期记忆）
- **`docker/`** —— 沙箱执行镜像

```bash
# 构建沙箱镜像
docker build -t coding-agent-sandbox:latest docker/

# 使用 docker-compose 部署完整服务
cd deploy
cp .env.example .env   # 编辑填入 API Key 与工作区路径
docker compose up -d
```

`docker-compose.yml` 会启动 Agent 主进程 + Postgres（长期记忆），并将宿主机的 Docker socket 挂载进容器以启动沙箱。

---

## 技术栈

**后端**：Python 3.11 · LangChain / LangGraph · FastAPI · Pydantic v2 · Tree-sitter · NetworkX · ChromaDB · Docker SDK · MCP · Structlog

**前端**：React 19 · TypeScript · Vite · Tailwind CSS v4 · Zustand · TanStack Query · CodeMirror · Recharts · i18next

**工程化**：uv / pip · pytest · ruff · mypy · black · isort · pnpm · vitest

---

## License

MIT
