"""Day 12: 沙箱内 shell 与文件工具。

Day 2 的文件工具改由沙箱 backend 执行，保证操作与隔离边界一致。
"""

from __future__ import annotations

from langchain.tools import tool

from sandbox.base import Sandbox
from sandbox.shell import ShellManager

# 全局绑定，由 registry 在初始化时注入
_SANDBOX: Sandbox | None = None
_SHELL: ShellManager | None = None


def bind(sandbox: Sandbox) -> None:
    global _SANDBOX, _SHELL
    _SANDBOX = sandbox
    _SHELL = ShellManager(sandbox)


def _require() -> tuple[Sandbox, ShellManager]:
    if _SANDBOX is None or _SHELL is None:
        raise RuntimeError("沙箱未绑定，请先调用 bind()")
    return _SANDBOX, _SHELL


@tool
def execute(command: str, timeout: int = 60) -> str:
    """在沙箱内执行 shell 命令。工作目录和环境变量跨调用保持。

    这是运行测试、安装依赖、启动服务的主要方式。

    Args:
        command: 要执行的命令。支持管道、重定向、多命令连接。
        timeout: 超时秒数，默认 60。
    """
    _, shell = _require()
    result = shell.execute(command, timeout=timeout)
    return result.to_text()


@tool
def sandbox_read(path: str) -> str:
    """从沙箱内读取文件。与本地 read_file 行为一致，但操作沙箱文件系统。

    Args:
        path: 相对于 /workspace 的文件路径。
    """
    sandbox, _ = _require()
    try:
        content = sandbox.read_file(path)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    if len(content) > 20000:
        return content[:20000] + f"\n... (truncated, {len(content)} chars total)"
    return content


@tool
def sandbox_write(path: str, content: str) -> str:
    """写入沙箱内文件。

    Args:
        path: 相对于 /workspace 的文件路径。
        content: 完整文件内容。
    """
    sandbox, _ = _require()
    try:
        sandbox.write_file(path, content)
        return f"OK: 已写入 {path}"
    except OSError as e:
        return f"ERROR: {e}"


# 沙箱内 ripgrep 封装，比 Python 版快 10-50 倍
@tool
def sandbox_grep(pattern: str, path: str = ".", context: int = 2) -> str:
    """在沙箱内用 ripgrep 搜索。比本地 grep_search 快得多。

    Args:
        pattern: 正则表达式。
        path: 搜索起始路径。
        context: 上下文行数。
    """
    _, shell = _require()
    # 使用 ripgrep，--no-heading 让输出更紧凑
    cmd = (
        f"rg --no-heading -n -C {context} "
        f"-g '!*.pyc' -g '!.git/*' -g '!node_modules/*' "
        f"{_shell_quote(pattern)} {_shell_quote(path)} | head -n 300"
    )
    result = shell.execute(cmd, timeout=30)
    if result.exit_code == 1:
        return f"未找到匹配 '{pattern}' 的内容"
    return result.to_text()


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


SANDBOX_TOOLS = ["execute", "sandbox_read", "sandbox_write", "sandbox_grep"]
