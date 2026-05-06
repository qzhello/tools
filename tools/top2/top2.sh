#!/bin/bash
# top2 - 简洁的系统监控 TUI（CPU/MEM/NET/DISK + 进程列表）

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
TOP2_PY="$SCRIPT_DIR/top2.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v top     &>/dev/null || { printf '✗ 找不到 top\n'     >&2; exit 1; }
command -v ps      &>/dev/null || { printf '✗ 找不到 ps\n'      >&2; exit 1; }
[[ -f "$TOP2_PY" ]] || { printf '✗ 找不到 %s\n' "$TOP2_PY" >&2; exit 1; }

exec python3 "$TOP2_PY" "$@"
