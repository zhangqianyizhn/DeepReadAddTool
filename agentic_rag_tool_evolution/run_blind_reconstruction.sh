#!/usr/bin/env bash
# 盲重建：Analyzer 从 train 60 题 baseline 轨迹诊断能力缺口，Repair Agent 生成候选工具。
# 支持 --dry-run（只校验输入，不调 API）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/scripts/_entry_common.sh"
run_entry "$HERE/scripts/blind_reconstruction.py" "$@"
