---
name: docker
description: Docker 镜像构建与容器编排
trigger: 当任务涉及 Dockerfile、docker-compose 或容器化部署时
category: original
tools: execute, sandbox_read
---

## Dockerfile 最佳实践

```dockerfile
FROM python:3.11-slim

# 1. 系统依赖（合并 RUN，清理缓存）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Python 依赖（利用缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 应用代码
COPY . .

# 4. 非 root 用户
RUN useradd -m appuser
USER appuser