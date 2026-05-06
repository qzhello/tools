#!/bin/bash
# pathx - 可视化 $PATH：每项是否存在/重复/binary 数，遮蔽检测，按名查找

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

set -e

_resolve="${BASH_SOURCE[0]}"
while [[ -L "$_resolve" ]]; do
    _dir="$(cd -P "$(dirname "$_resolve")" && pwd)"
    _link="$(readlink "$_resolve")"
    [[ "$_link" = /* ]] && _resolve="$_link" || _resolve="$_dir/$_link"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_resolve")" && pwd)"
PATHX_PY="$SCRIPT_DIR/pathx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$PATHX_PY" ]] || { printf '✗ 找不到 %s\n' "$PATHX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export PATHX_FORCE_COLOR=1
fi

exec python3 "$PATHX_PY" "$@"
