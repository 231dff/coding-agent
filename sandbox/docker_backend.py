"""Day 11: Docker 沙箱实现（保留 cwd/env）。"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container

import docker
from sandbox.base import ExecResult, Sandbox


class DockerSandbox(Sandbox):
    DEFAULT_IMAGE = "coding-agent-sandbox:latest"

    def __init__(
        self,
        workspace: str | Path,
        image: str = DEFAULT_IMAGE,
        memory_limit: str = "2g",
        cpu_limit: float = 2.0,
        network: bool = False,
        auto_build: bool = True,
    ):
        self.workspace = Path(workspace).resolve()
        self.image = image or "coding-agent-sandbox:latest"
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network_disabled = not network
        self.auto_build = auto_build

        self.client: docker.DockerClient | None = None
        self.container: Container | None = None

        # 会话状态（在宿主侧维护）
        self._cwd: str = "/workspace"
        self._env: dict[str, str] = {}

    def start(self) -> None:
        try:
            self.client = docker.from_env()
        except DockerException as e:
            raise RuntimeError(f"Docker 不可用: {e}") from e

        try:
            self.client.images.get(self.image)
        except ImageNotFound:
            if self.auto_build:
                self._build_image()
            else:
                raise RuntimeError(f"镜像 {self.image} 不存在，请先构建")

        self.container = self.client.containers.run(
            self.image,
            command=["sleep", "infinity"],
            detach=True,
            working_dir="/workspace",
            volumes={
                str(self.workspace): {"bind": "/workspace", "mode": "rw"},
            },
            mem_limit=self.memory_limit,
            nano_cpus=int(self.cpu_limit * 1e9),
            network_disabled=self.network_disabled,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE"],
            auto_remove=False,
            labels={"coding-agent": "sandbox"},
        )

    def _build_image(self) -> None:
        dockerfile_dir = Path(__file__).parent.parent / "docker"
        if not (dockerfile_dir / "Dockerfile").exists():
            raise FileNotFoundError(f"Dockerfile 不存在: {dockerfile_dir}")
        self.client.images.build(
            path=str(dockerfile_dir),
            tag=self.image,
            rm=True,
        )

    def stop(self) -> None:
        if self.container is not None:
            try:
                self.container.stop(timeout=5)
            except NotFound:
                pass
            try:
                self.container.remove(force=True)
            except NotFound:
                pass
            self.container = None

    def exec(
        self,
        command: str,
        timeout: int = 60,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        if self.container is None:
            raise RuntimeError("沙箱未启动，请先调用 start()")

        start = time.time()

        # 合并 cwd/env：显式传入 > 会话记忆
        eff_cwd = cwd or self._cwd
        eff_env = {**self._env, **(env or {})}

        # 处理 cd 命令：如果命令是 cd 开头，更新记忆
        stripped = command.strip()
        if stripped.startswith("cd ") and "&&" not in stripped:
            target = stripped[3:].strip()
            self._cwd = self._resolve_cwd(eff_cwd, target)
            return ExecResult(
                exit_code=0,
                stdout="",
                stderr="",
                duration_s=time.time() - start,
            )

        # 处理 export 命令
        if stripped.startswith("export ") and "&&" not in stripped:
            kv = stripped[len("export ") :].strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                self._env[k.strip()] = v.strip().strip("'\"")
            return ExecResult(
                exit_code=0,
                stdout="",
                stderr="",
                duration_s=time.time() - start,
            )

        try:
            exit_code, output = self.container.exec_run(
                cmd=["sh", "-c", command],
                workdir=eff_cwd,
                environment=eff_env,
                demux=True,
            )
        except Exception as e:
            return ExecResult(
                exit_code=-1,
                stdout="",
                stderr=f"执行失败: {e}",
                duration_s=time.time() - start,
            )

        duration = time.time() - start
        stdout_bytes, stderr_bytes = output if output else (b"", b"")

        MAX_BYTES = 200_000
        truncated = False
        full_path = None

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if len(stdout) + len(stderr) > MAX_BYTES:
            truncated = True
            full_path = self._save_full_output(stdout, stderr)
            stdout = stdout[: MAX_BYTES // 2]
            stderr = stderr[: MAX_BYTES // 2]

        return ExecResult(
            exit_code=exit_code or 0,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
            truncated=truncated,
            full_output_path=full_path,
        )

    @staticmethod
    def _resolve_cwd(base: str, target: str) -> str:
        if target.startswith("/"):
            return target
        if target == "..":
            return str(Path(base).parent)
        if target == ".":
            return base
        return str(Path(base) / target)

    def _save_full_output(self, stdout: str, stderr: str) -> str:
        out_dir = self.workspace / ".sandbox_outputs"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"exec_{int(time.time() * 1000)}.txt"
        path.write_text(
            f"=== STDOUT ===\n{stdout}\n=== STDERR ===\n{stderr}",
            encoding="utf-8",
        )
        return str(path.relative_to(self.workspace))

    def read_file(self, path: str) -> str:
        result = self.exec(f"cat {self._quote(path)}")
        if not result.ok:
            raise FileNotFoundError(f"读取失败: {path}: {result.stderr}")
        return result.stdout

    def write_file(self, path: str, content: str) -> None:
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = (
            f"mkdir -p $(dirname {self._quote(path)}) && "
            f"echo {encoded} | base64 -d > {self._quote(path)}"
        )
        result = self.exec(cmd)
        if not result.ok:
            raise OSError(f"写入失败: {path}: {result.stderr}")

    def upload_dir(self, local_dir: str | Path, remote_dir: str) -> None:
        local_dir = Path(local_dir)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            tar.add(str(local_dir), arcname=".")
        stream.seek(0)
        self.container.put_archive(remote_dir, stream.read())

    def download_dir(self, remote_dir: str, local_dir: str | Path) -> None:
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        stream, _ = self.container.get_archive(remote_dir)
        buf = io.BytesIO()
        for chunk in stream:
            buf.write(chunk)
        buf.seek(0)
        with tarfile.open(fileobj=buf) as tar:
            tar.extractall(str(local_dir))

    @staticmethod
    def _quote(s: str) -> str:
        return "'" + s.replace("'", "'\\''") + "'"

    def stats(self) -> dict:
        if self.container is None:
            return {}
        stats = self.container.stats(stream=False)
        return {
            "memory_usage_mb": stats["memory_stats"]["usage"] / 1024 / 1024,
            "cpu_percent": self._calc_cpu_percent(stats),
        }

    @staticmethod
    def _calc_cpu_percent(stats: dict) -> float:
        try:
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            sys_delta = (
                stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            )
            n_cpus = stats["cpu_stats"].get("online_cpus", 1)
            return (cpu_delta / sys_delta) * n_cpus * 100 if sys_delta > 0 else 0.0
        except (KeyError, ZeroDivisionError):
            return 0.0
