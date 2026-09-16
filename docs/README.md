# Coding Agent

基于 LangChain + LangGraph 的生产级代码编辑智能体。

## 快速开始

### 前置要求

- Python 3.11+
- Docker Engine
- 至少一个模型 API 密钥（OpenAI / Anthropic）

### 本地安装

```bash
# 克隆并安装
git clone <repo>
cd coding-agent

# 使用 uv 安装依赖
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# 配置环境变量
cp deploy/.env.example .env
# 编辑 .env，填入 API 密钥和工作区路径

# 构建沙箱镜像
docker build -t coding-agent-sandbox:latest docker/

# 运行
python -m agent.main "给 calc.py 的 add 函数添加 docstring"