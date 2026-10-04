import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sandbox.docker_backend import DockerSandbox

sb = DockerSandbox(workspace='.', network=False)
sb.start()
try:
    r1 = sb.exec('echo hello')
    print(f'[1] echo hello: exit={r1.exit_code} ok={r1.ok} stdout={r1.stdout!r}')

    r2 = sb.exec('exit 127')
    print(f'[2] exit 127:   exit={r2.exit_code} ok={r2.ok}')

    r3 = sb.exec('cd /tmp 2>/dev/null || cd .; pwd')
    print(f'[3] cd compound: exit={r3.exit_code} stdout={r3.stdout.strip()!r}')
    print(f'    sandbox._cwd = {sb._cwd!r}   (expected: /workspace)')

    r4 = sb.exec('cd /tmp')
    print(f'[4] pure cd:    exit={r4.exit_code} _cwd={sb._cwd!r}   (expected: /tmp)')

    r5 = sb.exec('pwd')
    print(f'[5] pwd:        exit={r5.exit_code} stdout={r5.stdout.strip()!r}   (expected: /tmp)')
finally:
    sb.stop()
