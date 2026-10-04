"""用法: python scripts/demo_verify.py <jsonl-path-or-glob>"""
import sys
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verification import TrajectoryVerifier, load_events


def main():
    if len(sys.argv) < 2:
        print('用法: python scripts/demo_verify.py <jsonl路径或通配符>')
        return

    raw = sys.argv[1]
    matches = glob.glob(raw) if ('*' in raw or '?' in raw) else [raw]
    if not matches:
        print(f'未找到匹配文件: {raw}')
        return

    matches.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
    path = Path(matches[0])

    if path.stat().st_size == 0:
        print(f'警告: {path} 是 0 字节文件')

    events = load_events(path)
    print(f'文件: {path.name} ({path.stat().st_size} bytes)')
    print(f'加载 {len(events)} 条事件')
    verifier = TrajectoryVerifier()
    diag = verifier.verify(task_id=path.stem, events=events)
    print('=' * 60)
    print(diag.summary)
    print('=' * 60)
    for d in diag.dimensions:
        print(f'[{d.severity.value:>6}] {d.name:<28} '
              f'{d.verdict.value:<9} conf={d.confidence:.2f}')
        if d.reason:
            print(f'         {d.reason}')


if __name__ == '__main__':
    main()
