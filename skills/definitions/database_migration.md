---
name: database_migration
description: 数据库 schema 迁移与版本管理
trigger: 当任务涉及数据库 schema 变更、迁移文件或 Alembic 时
category: original
tools: execute, sandbox_read
---

## Alembic 常用命令

```bash
# 初始化
alembic init migrations

# 生成迁移（自动检测模型变更）
alembic revision --autogenerate -m "add users table"

# 应用迁移
alembic upgrade head

# 回滚一个版本
alembic downgrade -1

# 查看历史
alembic history

# 查看当前版本
alembic current