---
name: python_testing
description: Python 测试配置、执行与调试
trigger: 当任务涉及 pytest、测试文件、测试失败或覆盖率时
category: original
tools: execute, sandbox_read, sandbox_write, sandbox_grep
---

## pytest 常用命令

```bash
# 运行全部测试
pytest

# 运行单个文件
pytest tests/test_foo.py

# 运行单个测试
pytest tests/test_foo.py::test_bar

# 显示详细输出
pytest -v

# 失败即停
pytest -x

# 显示 print 输出
pytest -s

# 覆盖率
pytest --cov=src --cov-report=term-missing