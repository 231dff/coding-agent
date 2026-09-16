"""Day 11: Docker 沙箱测试。

标记为 integration，本地无 Docker 时跳过。
"""

import pytest

from sandbox.docker_backend import DockerSandbox

pytestmark = pytest.mark.skipif(
    not __import__("shutil").which("docker"),
    reason="Docker 不可用",
)


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')\n")
    sb = DockerSandbox(tmp_path, network=False)
    sb.start()
    yield sb
    sb.stop()


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
