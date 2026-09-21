# 📊 Coding Agent 评测报告

**生成时间**: 2026-09-21 17:06:37
**模型**: `qwen:deepseek-v4-flash-0731`

## 🎯 核心指标

| 指标 | 数值 |
|------|------|
| **任务通过率** | **100.0%** (8/8) |
| 异常率 | 0.0% |
| 平均耗时 | 21.18s |
| P95 耗时 | 49.62s |
| 平均输入 Token | 26363 |
| 平均输出 Token | 696 |
| 平均缓存命中率 | 0.0% |
| **总成本** | **$0.2276** |
| **平均单任务成本** | **$0.0284** |

## 📂 分类别结果

| 类别 | 通过率 | 平均耗时 | 平均成本 |
|------|--------|----------|----------|
| bug_fix | 100.0% (2/2) | 40.0s | $0.0506 |
| dep_upgrade | 100.0% (1/1) | 13.4s | $0.0194 |
| multi_file | 100.0% (2/2) | 19.9s | $0.0295 |
| single_file | 100.0% (3/3) | 12.1s | $0.0160 |

## 🔍 回归检查

**状态**: ✅ 通过

```
✓ 通过率: 100.0% (基线 100.0%)
✓ 成本: $0.0284 (基线 $0.0288, -1.2%)
✓ 异常率: 0.0%
✓ [single_file]: 100.0% (基线 100.0%)
· 跳过门禁的类别: bug_fix(样本 2 < 3), dep_upgrade(样本 1 < 3), multi_file(样本 2 < 3)
```

## 📋 详细结果

| 任务 | 类别 | 结果 | 耗时 | 输入 Token | 输出 Token | 工具调用 |
|------|------|------|------|-----------|-----------|----------|
| fix_import_cycle | bug_fix | ✅ | 15.1s | 18713 | 475 | read_file, read_file, edit_file, execute |
| fix_off_by_one | bug_fix | ✅ | 64.9s | 75026 | 2013 | read_file, read_file, edit_file, search_tools, search_tools (+11) |
| upgrade_api_usage | dep_upgrade | ✅ | 13.4s | 18326 | 348 | grep_search, read_file, edit_file |
| add_param_with_callers | multi_file | ✅ | 21.3s | 29344 | 1002 | glob_files, glob_files, read_file, read_file, grep_search (+4) |
| rename_across_files | multi_file | ✅ | 18.5s | 24012 | 885 | glob_files, grep_search, read_file, grep_search, read_file (+2) |
| add_docstring | single_file | ✅ | 11.3s | 13610 | 281 | read_file, edit_file |
| fix_add_bug | single_file | ✅ | 11.4s | 13579 | 248 | read_file, edit_file |
| rename_function | single_file | ✅ | 13.6s | 18291 | 313 | read_file, edit_file, grep_search |
