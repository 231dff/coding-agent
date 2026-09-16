"""工具注册表：集中管理所有工具，便于按需加载和中间件过滤。"""
from langchain.tools import BaseTool
from tools.file_ops import (
    read_file, write_file, edit_file, glob_files, grep_search, ls_dir,
    set_workspace,
)


def build_default_tools(workspace: str) -> list[BaseTool]:
    """构建 Level 1 常驻工具集（Day 2 的 6 个核心文件工具）。"""
    set_workspace(workspace)
    return [
        read_file,
        write_file,
        edit_file,
        glob_files,
        grep_search,
        ls_dir,
    ]


# Level 2 技能和 Level 3 代码执行工具将在 Day 21-22 按需加载机制中接入
LEVEL1_TOOLS = ["read_file", "write_file", "edit_file", "glob_files", "grep_search", "ls_dir"]