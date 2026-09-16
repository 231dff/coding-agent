"""Day 11: 沙箱抽象接口。

定义后端无关的 Sandbox 接口，Docker 只是其中一种实现。
未来可替换为 E2B、Modal、Daytona 等云端沙箱。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    """一次命令执行的结果。"""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    truncated: bool = False
    full_output_path: str | None = None  # 超长输出的落盘路径

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_text(self, max_chars: int = 4000) -> str:
        """格式化为工具可返回的文本。"""
        parts = []
        if self.stdout:
            parts.append(f"STDOUT:\n{self.stdout}")
        if self.stderr:
            parts.append(f"STDERR:\n{self.stderr}")
        parts.append(f"EXIT: {self.exit_code}")
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, {len(text)} chars total)"
            if self.full_output_path:
                text += f"\n完整输出: {self.full_output_path}"
        return text


class Sandbox(ABC):
    """沙箱抽象基类。"""

    @abstractmethod
    def start(self) -> None:
        """启动沙箱。"""

    @abstractmethod
    def stop(self) -> None:
        """停止并销毁沙箱。"""

    @abstractmethod
    def exec(
        self,
        command: str,
        timeout: int = 60,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱中执行命令。"""

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取沙箱内文件。"""

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """写入沙箱内文件。"""

    @abstractmethod
    def upload_dir(self, local_dir: str | Path, remote_dir: str) -> None:
        """上传目录到沙箱。"""

    @abstractmethod
    def download_dir(self, remote_dir: str, local_dir: str | Path) -> None:
        """从沙箱下载目录。"""

    # 上下文管理器支持
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
