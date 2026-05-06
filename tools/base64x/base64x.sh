#!/bin/bash
# base64x - base64 双向自动识别，支持 url-safe / 文件 / 剪贴板进出

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
BASE64X_PY="$SCRIPT_DIR/base64x.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$BASE64X_PY" ]] || { printf '✗ 找不到 %s\n' "$BASE64X_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export BASE64X_FORCE_COLOR=1
fi

exec python3 "$BASE64X_PY" "$@"
