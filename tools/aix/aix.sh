#!/bin/bash
# aix - Claude Code token 用量统计，按天/模型/项目/会话聚合 + 条形图

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
AIX_PY="$SCRIPT_DIR/aix.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$AIX_PY" ]] || { printf '✗ 找不到 %s\n' "$AIX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export AIX_FORCE_COLOR=1
fi

exec python3 "$AIX_PY" "$@"
