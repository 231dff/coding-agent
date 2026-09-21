# 📊 Coding Agent 评测报告

**生成时间**: 2026-09-21 16:22:56
**模型**: `qwen:deepseek-v4-flash-0731`

## 🎯 核心指标

| 指标 | 数值 |
|------|------|
| **任务通过率** | **100.0%** (8/8) |
| 异常率 | 0.0% |
| 平均耗时 | 19.81s |
| P95 耗时 | 54.56s |
| 平均输入 Token | 26623 |
| 平均输出 Token | 722 |
| 平均缓存命中率 | 0.0% |
| **总成本** | **$1.1516** |
| **平均单任务成本** | **$0.1440** |

## 📂 分类别结果

| 类别 | 通过率 | 平均耗时 | 平均成本 |
|------|--------|----------|----------|
| bug_fix | 100.0% (2/2) | 32.1s | $0.1968 |
| dep_upgrade | 100.0% (1/1) | 13.2s | $0.0975 |
| multi_file | 100.0% (2/2) | 20.4s | $0.1609 |
| single_file | 100.0% (3/3) | 13.4s | $0.1129 |

## 📋 详细结果

| 任务 | 类别 | 结果 | 耗时 | 输入 Token | 输出 Token | 工具调用 |
|------|------|------|------|-----------|-----------|----------|
| fix_import_cycle | bug_fix | ✅ | 20.5s | 18764 | 970 | read_file, read_file, edit_file, grep_search |
| fix_off_by_one | bug_fix | ✅ | 43.7s | 52815 | 1407 | read_file, search_tools, search_tools, edit_file, run_tests (+6) |
| upgrade_api_usage | dep_upgrade | ✅ | 13.2s | 18359 | 380 | grep_search, read_file, edit_file |
| add_param_with_callers | multi_file | ✅ | 24.1s | 34366 | 1259 | glob_files, glob_files, read_file, read_file, grep_search (+5) |
| rename_across_files | multi_file | ✅ | 16.6s | 24144 | 696 | glob_files, grep_search, read_file, read_file, edit_file (+2) |
| add_docstring | single_file | ✅ | 11.3s | 18211 | 247 | glob_files, read_file, edit_file |
| fix_add_bug | single_file | ✅ | 11.7s | 13579 | 304 | read_file, edit_file |
| rename_function | single_file | ✅ | 17.4s | 32744 | 517 | glob_files, grep_search, read_file, edit_file, grep_search (+1) |
