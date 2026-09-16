"""Day 25: Git 操作 MCP Server。"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Git")


@mcp.tool()
def git_status(workspace: str = ".") -> str:
    """查看 git 状态。"""
    import subprocess

    result = subprocess.run(
        ["git", "-C", workspace, "status", "--short"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout or "(工作区干净)"


@mcp.tool()
def git_diff(workspace: str = ".", file: str = "") -> str:
    """查看 git diff。

    Args:
        workspace: 工作区路径。
        file: 可选，限定文件。
    """
    import subprocess

    cmd = ["git", "-C", workspace, "diff"]
    if file:
        cmd.append(file)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout[:5000] or "(无变更)"


@mcp.tool()
def git_log(workspace: str = ".", n: int = 10) -> str:
    """查看最近 N 条提交。

    Args:
        workspace: 工作区路径。
        n: 提交数量。
    """
    import subprocess

    result = subprocess.run(
        ["git", "-C", workspace, "log", f"-{n}", "--oneline"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout or "(无提交历史)"


@mcp.tool()
def git_commit(workspace: str, message: str, files: str = "") -> str:
    """创建提交。

    Args:
        workspace: 工作区路径。
        message: 提交信息。
        files: 逗号分隔的文件列表，为空则提交所有变更。
    """
    import subprocess

    if files:
        file_list = [f.strip() for f in files.split(",")]
        subprocess.run(
            ["git", "-C", workspace, "add"] + file_list,
            capture_output=True,
            text=True,
            timeout=30,
        )
    else:
        subprocess.run(
            ["git", "-C", workspace, "add", "-A"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    result = subprocess.run(
        ["git", "-C", workspace, "commit", "-m", message],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout or result.stderr


if __name__ == "__main__":
    mcp.run(transport="stdio")
