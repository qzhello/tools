#!/bin/bash
# epoch - 时间戳/日期双向转换

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

show_help() {
    cat <<'EOF'
epoch - 时间戳 ↔ 日期双向转换

用法:
  epoch                          显示当前时间所有格式
  epoch <时间戳>                 自动识别 10/13/16/19 位（秒/毫秒/微秒/纳秒）
  epoch '<日期字符串>'           ISO 8601、YYYY-MM-DD HH:MM:SS、YYYY/MM/DD 等
  epoch -c, --clip               从剪贴板读
  echo <值> | epoch              从管道读
  epoch -h | --help

示例:
  epoch                          # 现在
  epoch 1714492800               # Unix 秒
  epoch 1714492800000            # Unix 毫秒
  epoch '2024-04-30 15:30'       # 日期时间
  epoch '2024-04-30T15:30:00+08:00'

输出: Unix 秒/毫秒/微秒, ISO 8601, UTC, 北京时间, 本地时间, RFC 2822, 相对时间

环境变量:
  NO_COLOR=1                     关闭着色
  EPOCH_FORCE_COLOR=1            强制着色（即使 stdout 不是 TTY）
EOF
}

command -v python3 &>/dev/null || { printf '✗ 找不到 python3\n' >&2; exit 1; }
[[ -f "$EPOCH_PY" ]] || { printf '✗ 找不到 %s\n' "$EPOCH_PY" >&2; exit 1; }

# 选项：-h / -c / 其他
USE_CLIP=0
positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help|help) show_help; exit 0 ;;
        -c|--clip)      USE_CLIP=1; shift ;;
        --)             shift; positional+=("$@"); break ;;
        *)              positional+=("$1"); shift ;;
    esac
done

if [[ $USE_CLIP -eq 1 ]]; then
    command -v pbpaste &>/dev/null || { printf '✗ 需要 pbpaste\n' >&2; exit 1; }
    input="$(pbpaste)"
elif [[ ${#positional[@]} -gt 0 ]]; then
    input="${positional[*]}"
elif [[ ! -t 0 ]]; then
    input="$(cat)"
else
    input=""
fi

# 把空白裁掉
input="$(printf '%s' "$input" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

# stdout 是 TTY 时强制着色（python 端独立判断，这里再保险）
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    export EPOCH_FORCE_COLOR=1
fi

exec python3 "$EPOCH_PY" $input
