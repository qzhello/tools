#!/bin/bash
# dnsx - 多 resolver DNS 对比查询。bash 仅做环境处理；逻辑在 python。

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
DNSX_PY="$SCRIPT_DIR/dnsx.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
command -v dig     &>/dev/null || { printf '✗ 找不到 dig（macOS 自带 / Linux 装 bind-utils）\n' >&2; exit 1; }
[[ -f "$DNSX_PY" ]] || { printf '✗ 找不到 %s\n' "$DNSX_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export DNSX_FORCE_COLOR=1
fi

exec python3 "$DNSX_PY" "$@"
