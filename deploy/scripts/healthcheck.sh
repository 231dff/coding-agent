#!/usr/bin/env bash
# Day 30: 健康检查
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DEPLOY_DIR"

echo "=== 健康检查 ==="

# 1. 容器状态
echo ""
echo "[容器状态]"
docker compose ps

# 2. Agent 进程
echo ""
echo "[Agent 进程]"
if docker compose exec -T agent pgrep -f "agent.main" > /dev/null 2>&1; then
    echo "✓ Agent 进程运行中"
else
    echo "✗ Agent 进程未运行"
    exit 1
fi

# 3. 沙箱连通性
echo ""
echo "[沙箱连通性]"
if docker images | grep -q "coding-agent-sandbox"; then
    echo "✓ 沙箱镜像存在"
else
    echo "✗ 沙箱镜像缺失"
fi

# 4. Postgres
echo ""
echo "[Postgres]"
if docker compose exec -T postgres pg_isready -U agent > /dev/null 2>&1; then
    echo "✓ Postgres 就绪"
else
    echo "✗ Postgres 未就绪"
    exit 1
fi

# 5. 最近错误日志
echo ""
echo "[最近错误]"
ERRORS=$(docker compose logs --tail=100 agent 2>&1 | grep -i "error\|exception" | tail -5 || true)
if [ -z "$ERRORS" ]; then
    echo "✓ 无近期错误"
else
    echo "$ERRORS"
fi

echo ""
echo "=== 检查完成 ==="