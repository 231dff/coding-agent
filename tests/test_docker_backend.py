"""Day 11: Docker 沙箱测试。

标记为 integration，本地无 Docker 时跳过。

跳过条件（任一命中即 skip）：
- 不是 Linux/macOS（Windows runner 拉不到 linux 镜像）
- 没装 docker CLI
- docker daemon 不响应
"""

from __future__ import annotations

import platform
import shutil

import pytest

from sandbox.docker_backend import DockerSandbox


# ============================================================
# 环境检测
# ============================================================

def _docker_usable() -> bool:
    """检查当前环境是否可以跑本测试。

    三个条件：
    1. 不是 Windows（windows runner 默认跑 Windows 容器，拉不到 linux 镜像）
    2. docker CLI 存在
    3. docker daemon 能 ping 通
    """
    # 条件 1：Windows 直接跳过
    if platform.system() == "Windows":
        return False

    # 条件 2：docker CLI 存在
    if shutil.which("docker") is None:
        return False

    # 条件 3：daemon 响应
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_usable(),
    reason=(
        "需要 Linux Docker daemon。"
        "Windows runner / 无 Docker 环境 / daemon 未启动时跳过。"
    ),
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')\n")
    sb = DockerSandbox(tmp_path, network=False)
    sb.start()
    yield sb
    sb.stop()


# ============================================================
# 测试
# ============================================================

def test_exec_simple(sandbox):
    result = sandbox.exec("echo hello")
    assert result.ok
    assert "hello" in result.stdout


def test_exec_nonzero(sandbox):
    result = sandbox.exec("exit 2")
    assert result.exit_code == 2


def test_network_isolation(sandbox):
    result = sandbox.exec("curl -s --max-time 2 https://example.com || echo BLOCKED")
    assert "BLOCKED" in result.stdout


def test_file_roundtrip(sandbox):
    sandbox.write_file("test.txt", "hello world")
    assert "hello world" in sandbox.read_file("test.txt")


def test_workspace_mount(sandbox, tmp_path):
    # 宿主机改文件，沙箱立即可见
    (tmp_path / "new.txt").write_text("from host")
    result = sandbox.exec("cat /workspace/new.txt")
    assert "from host" in result.stdout