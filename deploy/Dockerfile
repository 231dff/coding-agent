FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 先复制依赖清单，利用缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 复制应用代码
COPY agent/ ./agent/
COPY codebase/ ./codebase/
COPY context/ ./context/
COPY middleware/ ./middleware/
COPY tools/ ./tools/
COPY skills/ ./skills/
COPY mcp/ ./mcp/
COPY memory/ ./memory/
COPY observability/ ./observability/
COPY evals/ ./evals/
COPY perf/ ./perf/
COPY sandbox/ ./sandbox/
COPY prompts/ ./prompts/
COPY queries/ ./queries/

# 非 root 用户
RUN useradd -m -u 1000 agent
USER agent

ENTRYPOINT ["uv", "run", "python", "-m", "agent.main"]