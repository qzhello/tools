#!/bin/bash
# tracex - 可视化路由追踪。bash 仅做环境处理；逻辑在 python。

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
TRACEX_PY="$SCRIPT_DIR/tracex.py"

command -v python3    &>/dev/null || { printf '✗ 找不到 python3\n'    >&2; exit 1; }
command -v traceroute &>/dev/null || { printf '✗ 找不到 traceroute\n' >&2; exit 1; }
[[ -f "$TRACEX_PY" ]] || { printf '✗ 找不到 %s\n' "$TRACEX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export TRACEX_FORCE_COLOR=1
fi

exec python3 "$TRACEX_PY" "$@"
