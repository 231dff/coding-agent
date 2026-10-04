# scripts/fix_pyproject.py
"""一次性地把 verification* 加进 pyproject.toml 的 include 数组。"""
import sys
import tomllib
from pathlib import Path

p = Path("pyproject.toml")
if not p.exists():
    print("找不到 pyproject.toml，请在项目根目录运行")
    sys.exit(1)

text = p.read_text(encoding="utf-8")

# 1. 检查是否已经包含
if '"verification*"' in text:
    print("[跳过] 已包含 verification*")
else:
    # 2. 在 "api*", 后加一行
    old = '    "api*",\n'
    new = '    "api*",\n    "verification*",\n'

    if old in text:
        text = text.replace(old, new, 1)
        p.write_bytes(text.encode("utf-8"))   # ★ 无 BOM 写入
        print("[OK] 已添加 verification*")
    else:
        print("[失败] 未找到 '    \"api*\",' 这一行，请手动编辑")
        # 打印 include 段附近的行，方便排查
        for i, line in enumerate(text.splitlines(), 1):
            if "include" in line or '"api*"' in line:
                print(f"  {i}: {line!r}")
        sys.exit(1)

# 3. 验证 TOML 可解析
try:
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    include = data["tool"]["setuptools"]["packages"]["find"]["include"]
    print("[OK] TOML 解析成功")
    print("     include =", include)
except Exception as e:
    print("[失败] TOML 解析失败:", e)
    sys.exit(1)
