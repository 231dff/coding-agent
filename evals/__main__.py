"""让 `python -m evals` 可以直接执行。"""

from __future__ import annotations

import sys

from evals.main import main

if __name__ == "__main__":
    sys.exit(main())