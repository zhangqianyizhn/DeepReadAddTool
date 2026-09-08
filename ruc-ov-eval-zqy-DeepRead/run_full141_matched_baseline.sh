#!/usr/bin/env bash
# 从零重建 FinanceBench 141 题 matched baseline（建索引 + 生成 + 评分）。
# 产物供 agentic_rag_tool_evolution/scripts/blind_reconstruction.py 使用。
# 支持 --dry-run（只校验数据集与环境，不调 API）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../agentic_rag_tool_evolution/scripts/_entry_common.sh"
run_entry "$HERE/../agentic_rag_tool_evolution/scripts/rebuild_baseline141.py" "$@"
