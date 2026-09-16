"""pytest 全局配置与共享 fixture。"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中（即使没装 -e 也能跑）
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def pytest_configure(config):
    """注册自定义标记，避免 unknown marker 警告。"""
    config.addinivalue_line("markers", "integration: 需要外部依赖（Docker 等）的测试")
    config.addinivalue_line("markers", "slow: 慢速测试")


@pytest.fixture
def fake_sandbox():
    """可复用的假沙箱 fixture。"""
    from sandbox.base import Sandbox, ExecResult

    class FakeSandbox(Sandbox):
        def start(self): pass
        def stop(self): pass
        def exec(self, command, timeout=60, cwd=None, env=None):
            return ExecResult(0, "", "", 0.0)
        def read_file(self, path): return ""
        def write_file(self, path, content): pass
        def upload_dir(self, local, remote): pass
        def download_dir(self, remote, local): pass

    return FakeSandbox()