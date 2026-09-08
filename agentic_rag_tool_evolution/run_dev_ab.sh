#!/usr/bin/env bash
# Dev 20 严格 A/B：同模型 Baseline vs AI 生成工具方案 + 固定 Judge。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/scripts/_entry_common.sh"
run_entry "$HERE/scripts/dev_ab.py" "$@"
