#!/bin/bash
# pingx - 实时可视化 ping。bash 仅做环境处理；逻辑在 python。

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

set -e

# 解析 symlink，找到脚本真实所在目录
_resolve="${BASH_SOURCE[0]}"
while [[ -L "$_resolve" ]]; do
    _dir="$(cd -P "$(dirname "$_resolve")" && pwd)"
    _link="$(readlink "$_resolve")"
    [[ "$_link" = /* ]] && _resolve="$_link" || _resolve="$_dir/$_link"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_resolve")" && pwd)"
PINGX_PY="$SCRIPT_DIR/pingx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v ping    &>/dev/null || { printf '✗ 找不到 ping\n'    >&2; exit 1; }
[[ -f "$PINGX_PY" ]] || { printf '✗ 找不到 %s\n' "$PINGX_PY" >&2; exit 1; }

# 终端时强制保留颜色（python 子进程会检测父进程 TTY 而非自身 TTY）
if [[ -t 1 ]]; then
    export PINGX_FORCE_COLOR=1
fi

exec python3 "$PINGX_PY" "$@"
