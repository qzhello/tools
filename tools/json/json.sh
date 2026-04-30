#!/bin/bash
# json - JSON 美化工具（带宽容解析、文件/目录就地美化、错误高亮）

# 强制 UTF-8 locale，避免 macOS 自带 bash 3.2 在默认 C locale 下截断中文
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
PRETTIFY="$SCRIPT_DIR/prettify.py"
COLORIZE="$SCRIPT_DIR/colorize.py"

show_help() {
    cat <<'EOF'
json - JSON 美化工具

输入模式:
  json '<json>'              直接传 JSON 字符串（务必单引号包住）
  echo '<json>' | json       从管道读
  json                       从剪贴板读 (pbpaste)
  json <文件>                就地美化单个文件，原文件备份为 <文件>.bak
  json <目录>                递归美化目录下所有 *.json，每个文件备份 .bak

选项:
  -n, --dry-run              只报告不写盘（仅文件/目录模式）
      --no-backup            就地写盘时不生成 .bak
  -h, --help

特性:
  • 美化结果同时打到 stdout 与剪贴板 (pbcopy)，文件/目录模式不动剪贴板
  • 终端显示带语法高亮，复制/管道自动去色
  • 中文原样保留（不转 \uXXXX）
  • 解析失败时高亮错误行 + 列箭头
  • 宽容解析顺序：strict → 去注释/尾逗号 → Python/JS 对象字面量 → 原样输出

环境变量:
  NO_COLOR=1                 强制关闭颜色（遵循 https://no-color.org）

依赖: pbcopy / pbpaste / python3（macOS 自带）
EOF
}

# 环境检查
for cmd in pbcopy pbpaste python3; do
    command -v "$cmd" &>/dev/null || { printf '✗ 找不到 %s\n' "$cmd" >&2; exit 1; }
done
[[ -f "$PRETTIFY" ]] || { printf '✗ 找不到 %s\n' "$PRETTIFY" >&2; exit 1; }

# ========== 选项解析 ==========

DRY_RUN=0
BACKUP=1
positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help|help) show_help; exit 0 ;;
        -n|--dry-run)   DRY_RUN=1; shift ;;
        --no-backup)    BACKUP=0; shift ;;
        --)             shift; positional+=("$@"); break ;;
        *)              positional+=("$1"); shift ;;
    esac
done
set -- "${positional[@]}"

# ========== 单个内容美化（核心） ==========
# 用法: prettify_text "<input>" "<source-label>"
# 设置全局变量: PRETTY、MODE、ERR_FILE_CONTENT、PRETTY_RC
prettify_text() {
    local input="$1"
    local _err
    _err="$(mktemp)"

    set +e
    PRETTY="$(printf '%s' "$input" | python3 "$PRETTIFY" 2>"$_err")"
    PRETTY_RC=$?
    set -e

    MODE="$(sed -n 's/^mode=//p' "$_err" | head -1)"
    # 去掉首行 mode=...，剩下的是高亮错误（如有）
    ERR_BLOCK="$(sed '1{/^mode=/d;}' "$_err")"
    rm -f "$_err"
}

# 渲染输入模式（参数/管道/剪贴板）的状态消息到 stderr
report_inline_status() {
    local src="$1"
    case "$MODE" in
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
            [[ -n "$ERR_BLOCK" ]] && printf '%s\n' "$ERR_BLOCK" >&2
            ;;
    esac
}

# 显示美化结果（TTY 上色，否则纯文本）
emit_pretty() {
    if [[ -t 1 && -z "${NO_COLOR:-}" && "$MODE" != "raw" && -f "$COLORIZE" ]]; then
        printf '%s\n' "$PRETTY" | python3 "$COLORIZE"
    else
        printf '%s\n' "$PRETTY"
    fi
}

# ========== 文件模式 ==========

# 处理单个文件，返回值: 0=已美化, 1=无变化, 2=解析失败
process_file() {
    local file="$1"
    local content; content="$(cat "$file")"

    if [[ -z "${content// /}" ]]; then
        printf '  %s — 跳过（空文件）\n' "$file" >&2
        return 1
    fi

    prettify_text "$content"

    if [[ "$MODE" == "raw" ]]; then
        printf '  ✗ %s — 解析失败\n' "$file" >&2
        [[ -n "$ERR_BLOCK" ]] && printf '%s\n' "$ERR_BLOCK" | sed 's/^/    /' >&2
        return 2
    fi

    # 与原内容比较（忽略尾部换行差异）
    if [[ "${content%$'\n'}" == "$PRETTY" ]]; then
        printf '  · %s — 已格式化\n' "$file" >&2
        return 1
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  ~ %s — 将被美化（dry-run）\n' "$file" >&2
        return 0
    fi

    if [[ $BACKUP -eq 1 ]]; then
        cp "$file" "$file.bak"
    fi
    printf '%s\n' "$PRETTY" > "$file"

    case "$MODE" in
        strict)  printf '  ✓ %s\n' "$file" >&2 ;;
        lenient) printf '  ✓ %s（含注释/尾逗号，已宽容解析）\n' "$file" >&2 ;;
        pyobj)   printf '  ✓ %s（按 Python/JS 字面量解析）\n' "$file" >&2 ;;
    esac
    return 0
}

# 找到所有 *.json 并逐个处理
process_dir() {
    local dir="$1"
    local n_done=0 n_skip=0 n_fail=0

    printf '扫描目录: %s\n' "$dir" >&2
    while IFS= read -r -d '' f; do
        local rc=0
        process_file "$f" || rc=$?
        case $rc in
            0) n_done=$((n_done + 1)) ;;
            1) n_skip=$((n_skip + 1)) ;;
            2) n_fail=$((n_fail + 1)) ;;
        esac
    done < <(find "$dir" -type f -name '*.json' -not -name '*.bak' -print0)

    printf '\n总结: 美化 %d 个，跳过 %d 个，失败 %d 个' "$n_done" "$n_skip" "$n_fail" >&2
    [[ $DRY_RUN -eq 1 ]] && printf '（dry-run，未写盘）' >&2
    printf '\n' >&2

    [[ $n_fail -gt 0 ]] && return 2
    return 0
}

# ========== 输入路由 ==========

# 1) 第一个参数是已存在的文件 → 文件模式
# 2) 第一个参数是已存在的目录 → 目录模式
# 3) 否则按字符串/管道/剪贴板处理
if [[ $# -eq 1 && -f "$1" ]]; then
    rc=0
    process_file "$1" || rc=$?
    [[ $rc -eq 2 ]] && exit 2
    exit 0
fi

if [[ $# -eq 1 && -d "$1" ]]; then
    process_dir "$1"
    exit $?
fi

# ----- 内联模式（参数 / 管道 / 剪贴板） -----

if [[ $# -gt 0 ]]; then
    input="$*"; src="参数"
elif [[ ! -t 0 ]]; then
    input="$(cat)"; src="管道"
else
    input="$(pbpaste)"; src="剪贴板"
fi

if [[ -z "${input// /}" ]]; then
    printf '✗ 输入为空（来源: %s）\n' "$src" >&2
    exit 1
fi

prettify_text "$input"

# 剪贴板永远拿无颜色版本
printf '%s' "$PRETTY" | pbcopy

emit_pretty
report_inline_status "$src"

exit $PRETTY_RC
