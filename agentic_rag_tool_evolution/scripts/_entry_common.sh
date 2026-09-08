#!/usr/bin/env bash
# 公共入口逻辑：被各 run_*.sh source，不要直接执行。
# 提供 run_entry <script.py> [args...]：
#   - 使用 ruc-ov-eval-zqy-DeepRead/.venv 的统一环境；
#   - macOS 上用 caffeinate -i 防止长时间运行期间自动休眠（Linux 无此问题，直接执行）；
#   - 强制 UTF-8，避免日志中文乱码。

_ENTRY_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_EVOLUTION_ROOT="$(dirname "$_ENTRY_COMMON_DIR")"
WORKSPACE_ROOT="$(dirname "$TOOL_EVOLUTION_ROOT")"
VENV_PYTHON="$WORKSPACE_ROOT/ruc-ov-eval-zqy-DeepRead/.venv/bin/python"

run_entry() {
    if [[ ! -x "$VENV_PYTHON" ]]; then
        echo "[错误] 找不到统一环境：$VENV_PYTHON" >&2
        echo "请先执行：cd \"$WORKSPACE_ROOT/ruc-ov-eval-zqy-DeepRead\" && uv sync" >&2
        exit 1
    fi
    export PYTHONUTF8=1
    export PYTHONIOENCODING=utf-8
    if [[ "$(uname -s)" == "Darwin" ]] && command -v caffeinate >/dev/null 2>&1; then
        caffeinate -i "$VENV_PYTHON" "$@"
    else
        "$VENV_PYTHON" "$@"
    fi
}
