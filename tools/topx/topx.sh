#!/bin/bash
# topx - 简洁的系统监控 TUI（CPU/MEM/NET/DISK + 进程列表）

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
TOPX_PY="$SCRIPT_DIR/topx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v top     &>/dev/null || { printf '✗ 找不到 top\n'     >&2; exit 1; }
command -v ps      &>/dev/null || { printf '✗ 找不到 ps\n'      >&2; exit 1; }
command -v netstat &>/dev/null || { printf '✗ 找不到 netstat\n' >&2; exit 1; }
command -v iostat  &>/dev/null || { printf '✗ 找不到 iostat\n'  >&2; exit 1; }
[[ -f "$TOPX_PY" ]] || { printf '✗ 找不到 %s\n' "$TOPX_PY" >&2; exit 1; }

exec python3 "$TOPX_PY" "$@"
