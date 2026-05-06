#!/bin/bash
# loadx - 一句话告诉你机器现在累在哪：CPU/内存/网络/磁盘/电池 的瓶颈点 + Top 消耗

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
LOADX_PY="$SCRIPT_DIR/loadx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$LOADX_PY" ]] || { printf '✗ 找不到 %s\n' "$LOADX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export LOADX_FORCE_COLOR=1
fi

exec python3 "$LOADX_PY" "$@"
