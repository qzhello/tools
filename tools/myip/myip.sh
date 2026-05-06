#!/bin/bash
# myip - 公网 IP + ISP + 地理位置 + 本机网卡 IP，多源对比

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
MYIP_PY="$SCRIPT_DIR/myip.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$MYIP_PY" ]] || { printf '✗ 找不到 %s\n' "$MYIP_PY" >&2; exit 1; }

if [[ -t 1 ]]; then
    export MYIP_FORCE_COLOR=1
fi

exec python3 "$MYIP_PY" "$@"
