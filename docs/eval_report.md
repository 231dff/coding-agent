# 📊 Coding Agent 评测报告

**生成时间**: 2026-09-21 17:31:30
**模型**: `qwen:deepseek-v4-flash-0731`

## 🎯 核心指标

| 指标 | 数值 |
|------|------|
| **任务通过率** | **100.0%** (8/8) |
| 异常率 | 0.0% |
| 平均耗时 | 21.49s |
| P95 耗时 | 40.27s |
| 平均输入 Token | 25284 |
| 平均输出 Token | 697 |
| 平均缓存命中率 | 0.0% |
| **总成本** | **$0.2190** |
| **平均单任务成本** | **$0.0274** |

## 📂 分类别结果

| 类别 | 通过率 | 平均耗时 | 平均成本 |
|------|--------|----------|----------|
| bug_fix | 100.0% (2/2) | 33.7s | $0.0431 |
| dep_upgrade | 100.0% (1/1) | 14.2s | $0.0193 |
| multi_file | 100.0% (2/2) | 25.3s | $0.0303 |
| single_file | 100.0% (3/3) | 13.2s | $0.0177 |

## 🔍 回归检查

**状态**: ✅ 通过

```
✓ 通过率: 100.0% (基线 100.0%)
✓ 成本: $0.0274 (基线 $0.0284, -3.8%)
✓ 异常率: 0.0%
✓ [single_file]: 100.0% (基线 100.0%)
· 跳过门禁的类别: bug_fix(样本 2 < 3), dep_upgrade(样本 1 < 3), multi_file(样本 2 < 3)
```

## 📋 详细结果

| 任务 | 类别 | 结果 | 耗时 | 输入 Token | 输出 Token | 工具调用 |
|------|------|------|------|-----------|-----------|----------|
| fix_import_cycle | bug_fix | ✅ | 23.0s | 28690 | 874 | glob_files, read_file, read_file, edit_file, read_file (+2) |
| fix_off_by_one | bug_fix | ✅ | 44.5s | 51368 | 1174 | read_file, read_file, edit_file, search_tools, search_tools (+6) |
| upgrade_api_usage | dep_upgrade | ✅ | 14.2s | 18281 | 347 | grep_search, read_file, edit_file |
| add_param_with_callers | multi_file | ✅ | 32.4s | 29599 | 1719 | read_file, read_file, grep_search, edit_file, edit_file (+3) |
| rename_across_files | multi_file | ✅ | 18.3s | 23915 | 617 | glob_files, grep_search, read_file, read_file, edit_file (+2) |
| add_docstring | single_file | ✅ | 11.5s | 13609 | 240 | read_file, edit_file |
| fix_add_bug | single_file | ✅ | 12.1s | 13579 | 219 | read_file, edit_file |
| rename_function | single_file | ✅ | 16.0s | 23233 | 385 | glob_files, grep_search, read_file, edit_file, grep_search |
