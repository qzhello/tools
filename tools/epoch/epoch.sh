#!/bin/bash
# epoch - 时间戳/日期双向转换。bash 仅做环境处理；选项交给 python。

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

set -e

# 解析 symlink，找到脚本真实所在目录
_resolve="${BASH_SOURCE[0]}"
while [[ -L "$_resolve" ]]; do
    _dir="$(cd -P "$(dirname "$_resolve")" && pwd)"
    _link="$(readlink "$_resolve")"
    [[ "$_link" = /* ]] && _resolve="$_link" || _resolve="$_dir/$_link"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_resolve")" && pwd)"
EPOCH_PY="$SCRIPT_DIR/epoch.py"

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$EPOCH_PY" ]] || { printf '✗ 找不到 %s\n' "$EPOCH_PY" >&2; exit 1; }

exec python3 "$EPOCH_PY" "$@"
