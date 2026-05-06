#!/bin/bash
# portx - 列出本机监听端口 + 进程，识别常见服务，支持 -k 杀进程

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
PORTX_PY="$SCRIPT_DIR/portx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v lsof    &>/dev/null || { printf '✗ 找不到 lsof\n'    >&2; exit 1; }
[[ -f "$PORTX_PY" ]] || { printf '✗ 找不到 %s\n' "$PORTX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export PORTX_FORCE_COLOR=1
fi

exec python3 "$PORTX_PY" "$@"
