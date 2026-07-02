#!/bin/bash
# cmd-alias - 常用命令快捷别名管理（shell 入口为 a），输入 "a <前缀>" 按 Tab 行内展开/循环匹配命令
# 别名执行与 Tab 展开由 source.sh 在当前 shell 实现，本脚本负责增删查管理

set -e

ALIASES_FILE="${CMD_ALIASES_FILE:-$HOME/.cmd-aliases.conf}"
VERSION="1.0.0"

# 名称仅限字母/数字/_/-，且不能与子命令冲突
_valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
    case "$1" in
        add|rm|list|ls|help) return 1 ;;
    esac
    return 0
}

cmd_add() {
    if [[ $# -lt 2 ]]; then
        echo "用法: a add <名称> \"<完整命令>\""
        echo "示例: a add cc \"claude --dangerously-skip-permissions --permission-mode=bypassPermissions\""
        return 1
    fi

    local name="$1"; shift
    local cmd="$*"

    if ! _valid_name "$name"; then
        echo "✗ 非法名称: ${name}（仅限字母/数字/_/-，且不能是 add/rm/list/help）"
        return 1
    fi

    # 覆盖同名旧记录
    if [[ -f "$ALIASES_FILE" ]] && grep -q "^${name}|" "$ALIASES_FILE"; then
        sed -i '' "/^${name}|/d" "$ALIASES_FILE"
    fi
    echo "${name}|${cmd}" >> "$ALIASES_FILE"
    echo "✓ 已添加: ${name} -> ${cmd}"
}

cmd_list() {
    if [[ ! -s "$ALIASES_FILE" ]]; then
        echo "暂无别名。使用 a add <名称> \"<命令>\" 添加"
        return
    fi

    printf "%-12s %s\n" "名称" "命令"
    printf "%-12s %s\n" "----" "----"
    local line
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        printf "%-12s %s\n" "${line%%|*}" "${line#*|}"
    done < "$ALIASES_FILE"
}

cmd_rm() {
    if [[ -z "$1" ]]; then
        echo "用法: a rm <名称>"
        return 1
    fi

    local name="$1"
    if grep -q "^${name}|" "$ALIASES_FILE" 2>/dev/null; then
        sed -i '' "/^${name}|/d" "$ALIASES_FILE"
        echo "✓ 已删除: ${name}"
    else
        echo "✗ 未找到别名: ${name}"
        return 1
    fi
}

cmd_help() {
    cat <<'EOF'
cmd-alias (a) - 常用命令快捷别名

用法:
  a add <名称> "<完整命令>"    注册别名（同名覆盖）
  a rm <名称>                  删除别名
  a list                       列出所有别名
  a <名称> [额外参数...]       执行注册的命令
  a help                       显示帮助

Tab 展开（zsh）:
  输入 "a <前缀>" 后按 Tab，行内展开为匹配的完整命令；
  连按 Tab 在多条候选（注册别名 + shell 历史）间循环切换；
  回车执行展开后的真实命令。

示例:
  a add cc "claude --dangerously-skip-permissions --permission-mode=bypassPermissions"
  a cc                          直接启动
  a claude<Tab>                 展开为历史中匹配 claude 开头的完整命令

存储:
  ~/.cmd-aliases.conf，每行格式: 名称|完整命令
EOF
}

main() {
    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        add)     cmd_add "$@" ;;
        list|ls) cmd_list ;;
        rm)      cmd_rm "$@" ;;
        help|--help|-h) cmd_help ;;
        *)
            echo "未知命令: $cmd"
            cmd_help
            return 1
            ;;
    esac
}

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"
