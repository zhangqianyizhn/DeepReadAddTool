#!/usr/bin/env bash
# 冻结 Test 61：SHA-256 锁定候选/策略/模型/划分后运行最终 A/B（只运行一次）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/scripts/_entry_common.sh"
run_entry "$HERE/scripts/frozen_test61.py" "$@"
