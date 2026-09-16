---
name: code-review
category: 评审与诊断
description: 代码评审。触发：用户说"review"、"评审"、"PR 看看"、"diff 看一下"、"从 X 开始的改动"。不触发：只是读代码、只是解释代码、只是跑测试。
disable_model_invocation: false
tools:
  - read_file
  - grep_search
  - find_callers
---

# Code Review 技能

## 何时使用

- 用户说"评审一下"、"check 一下"、"review 这个 PR"
- 用户说"看看从 X 开始的改动"
- 实现完成后主动做质量检查
- 合并前检查

## 何时不用

- 用户只是问"这段代码干什么" → 直接解释
- 只改了一行配置 → 直接改
- 只是跑测试 → 用 `run_tests`

## 评审维度

1. **正确性**：逻辑、边界条件、错误处理
2. **可读性**：命名、注释、复杂度
3. **安全性**：注入、越权、敏感信息
4. **性能**：N+1、无界循环、内存
5. **一致性**：是否符合项目规范

## 工作流程

1. 用 `read_file` 读取所有相关文件
2. 用 `find_callers` 检查改动影响范围
3. 按上面 5 个维度逐项检查
4. 输出结构化报告

## 输出格式
