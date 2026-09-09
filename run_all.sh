#!/usr/bin/env bash
# 单命令全流程：三个数据集的工具演化闭环（划分 → baseline → 盲重建 → dev A/B → 修复 → 冻结 test）。
# 用法：
#   ./run_all.sh                          # 全部三个数据集
#   ./run_all.sh --datasets financebench  # 只跑 FinanceBench
#   ./run_all.sh --dry-run                # 只预检，不调 API
# 数据根目录可用 DEEPREAD_DATA_ROOT 覆盖（默认 <workspace>/Data）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/agentic_rag_tool_evolution/scripts/_entry_common.sh"
run_entry "$HERE/run_all.py" "$@"
