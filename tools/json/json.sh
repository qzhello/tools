#!/bin/bash
# json - JSON 美化工具（带宽容解析）

# 强制 UTF-8 locale，避免 macOS 自带 bash 3.2 在默认 C locale 下截断中文
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

set -e

# 解析 symlink，找到脚本真实所在目录（install.sh 通过 symlink 安装到 PATH）
_resolve="${BASH_SOURCE[0]}"
while [[ -L "$_resolve" ]]; do
    _dir="$(cd -P "$(dirname "$_resolve")" && pwd)"
    _link="$(readlink "$_resolve")"
    [[ "$_link" = /* ]] && _resolve="$_link" || _resolve="$_dir/$_link"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_resolve")" && pwd)"
PRETTIFY="$SCRIPT_DIR/prettify.py"

show_help() {
    cat <<'EOF'
json - JSON 美化工具

用法:
  json '<json>'              直接传 JSON 字符串（务必单引号包住）
  echo '<json>' | json       从管道读
  json                       从剪贴板读 (pbpaste)
  json -h | --help

特性:
  • 美化结果同时打到 stdout 与剪贴板 (pbcopy)
  • 中文原样保留（不转 \uXXXX）
  • 宽容解析：依次尝试
      1. 严格 JSON
      2. 去注释 / 去尾随逗号 后再解析
      3. Python dict / JS 对象字面量（单引号、True/False/None）
      4. 全部失败时原样输出 + 警告

依赖: pbcopy / pbpaste / python3（均 macOS 自带）
EOF
}

# 环境检查
for cmd in pbcopy pbpaste python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "✗ 找不到 $cmd" >&2
        exit 1
    fi
done
[[ -f "$PRETTIFY" ]] || { echo "✗ 找不到 $PRETTIFY" >&2; exit 1; }

case "${1:-}" in
    -h|--help|help) show_help; exit 0 ;;
esac

# ========== 决定输入来源 ==========

if [[ $# -gt 0 ]]; then
    input="$*"
    src="参数"
elif [[ ! -t 0 ]]; then
    input="$(cat)"
    src="管道"
else
    input="$(pbpaste)"
    src="剪贴板"
fi

if [[ -z "${input// /}" ]]; then
    echo "✗ 输入为空（来源: $src）" >&2
    exit 1
fi

# ========== 调用 python 美化器 ==========
# stdout 拿美化结果，stderr 拿 mode= / err= 元信息

err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT

set +e
pretty="$(printf '%s' "$input" | python3 "$PRETTIFY" 2>"$err_file")"
rc=$?
set -e

mode="$(sed -n 's/^mode=//p' "$err_file")"
errmsg="$(sed -n 's/^err=//p' "$err_file")"

# ========== 输出 + 复制 ==========

printf '%s\n' "$pretty"
printf '%s' "$pretty" | pbcopy

case "$mode" in
    strict)
        printf '✓ 已复制到剪贴板（来源: %s）\n' "$src" >&2
        ;;
    lenient)
        printf '⚠ 输入含注释或尾随逗号，已宽容解析后美化（来源: %s）\n' "$src" >&2
        printf '✓ 已复制到剪贴板\n' >&2
        ;;
    pyobj)
        printf '⚠ 输入不是合法 JSON，按 Python/JS 对象字面量解析（来源: %s）\n' "$src" >&2
        printf '✓ 已复制到剪贴板\n' >&2
        ;;
    raw|*)
        printf '⚠ 无法解析为 JSON，已原样复制（来源: %s）\n' "$src" >&2
        [[ -n "$errmsg" ]] && printf '  原始错误: %s\n' "$errmsg" >&2
        ;;
esac

exit $rc
