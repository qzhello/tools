#!/bin/bash
# ports - 列出监听端口 + 进程。bash 仅做环境处理；逻辑在 python。

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
PORTS_PY="$SCRIPT_DIR/ports.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v lsof    &>/dev/null || { printf '✗ 找不到 lsof\n'    >&2; exit 1; }
[[ -f "$PORTS_PY" ]] || { printf '✗ 找不到 %s\n' "$PORTS_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export PORTS_FORCE_COLOR=1
fi

exec python3 "$PORTS_PY" "$@"
