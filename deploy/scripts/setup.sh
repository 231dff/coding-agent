#!/usr/bin/env bash
# Day 30: 一键启动脚本
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DEPLOY_DIR")"

echo "=== Coding Agent 部署脚本 ==="
echo "项目根: $PROJECT_ROOT"

# 1. 检查前置
echo ""
echo "[1/5] 检查前置依赖..."

if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "错误: Docker daemon 未运行"
    exit 1
fi

echo "✓ Docker 可用"

# 2. 检查 .env
echo ""
echo "[2/5] 检查环境变量..."

if [ ! -f "$DEPLOY_DIR/.env" ]; then
    if [ -f "$DEPLOY_DIR/.env.example" ]; then
        cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
        echo "已从 .env.example 创建 .env"
        echo "请编辑 $DEPLOY_DIR/.env 填入 API 密钥和工作区路径"
        exit 1
    else
        echo "错误: 找不到 .env.example"
        exit 1
    fi
fi

# 加载 .env
set -a
source "$DEPLOY_DIR/.env"
set +a

if [ -z "${WORKSPACE_PATH:-}" ]; then
    echo "错误: WORKSPACE_PATH 未设置"
    exit 1
fi

if [ ! -d "$WORKSPACE_PATH" ]; then
    echo "错误: 工作区不存在: $WORKSPACE_PATH"
    exit 1
fi

echo "✓ 工作区: $WORKSPACE_PATH"

# 3. 构建沙箱镜像
echo ""
echo "[3/5] 构建沙箱镜像..."

if ! docker images | grep -q "coding-agent-sandbox"; then
    docker build -t coding-agent-sandbox:latest "$PROJECT_ROOT/docker"
    echo "✓ 沙箱镜像已构建"
else
    echo "✓ 沙箱镜像已存在"
fi

# 4. 启动服务
echo ""
echo "[4/5] 启动服务..."

cd "$DEPLOY_DIR"
docker compose up -d --build

# 5. 健康检查
echo ""
echo "[5/5] 等待服务就绪..."

for i in {1..30}; do
    if docker compose ps | grep -q "healthy\|running"; then
        break
    fi
    sleep 1
done

echo ""
echo "=== 部署完成 ==="
echo ""
echo "Agent 容器: $(docker compose ps -q agent)"
echo "Postgres:   $(docker compose ps -q postgres)"
echo ""
echo "查看日志: docker compose logs -f agent"
echo "进入容器: docker compose exec agent bash"
echo "停止服务: docker compose down"