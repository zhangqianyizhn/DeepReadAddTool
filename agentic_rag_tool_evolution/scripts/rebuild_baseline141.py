"""兼容入口：FinanceBench 141 题 matched baseline 重建。

实现已泛化到 run_baseline.py（支持 --dataset）；本文件仅保留原命令形态。
跨平台入口：`ruc-ov-eval-zqy-DeepRead/run_full141_matched_baseline.sh`。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_baseline  # noqa: E402

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--dataset", "financebench", *sys.argv[1:]]
    raise SystemExit(run_baseline.main())
