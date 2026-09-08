#!/usr/bin/env bash
# Round 2：Repair Agent 读取 dev 反馈后自主修复工具，并重跑修复组 20 题。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/scripts/_entry_common.sh"
run_entry "$HERE/scripts/repair_round2.py" "$@"
