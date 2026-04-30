#!/bin/bash
# ssh-alias - SSH 快捷登录管理工具
# 支持密钥免密登录，以及密码登录（密码存储于 macOS Keychain）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ALIASES_FILE="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"
KEYCHAIN_SERVICE="${SSH_ALIAS_KEYCHAIN_SERVICE:-ssh-alias}"
VERSION="1.1.0"

# ========== Keychain 助手（macOS） ==========

_keychain_available() {
    command -v security &>/dev/null
}

_keychain_set() {
    local name="$1" pass="$2"
    security add-generic-password -U \
        -s "$KEYCHAIN_SERVICE" -a "$name" -w "$pass" \
        -j "ssh-alias managed entry" >/dev/null
}

_keychain_get() {
    local name="$1"
    security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$name" -w 2>/dev/null
}

_keychain_delete() {
    local name="$1"
    security delete-generic-password -s "$KEYCHAIN_SERVICE" -a "$name" &>/dev/null || true
}

# ========== 核心函数 ==========

_load_aliases() {
    [[ ! -f "$ALIASES_FILE" ]] && return
    while IFS='|' read -r name target port method; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        _define_alias "$name" "$target" "$port" "$method"
    done < "$ALIASES_FILE"
}

# 运行时取密码并执行 ssh —— 由 keychain 模式的 shell 函数调用
_ssh_alias_connect() {
    local name="$1" target="$2" port="$3"
    local pass
    pass="$(_keychain_get "$name")"
    if [[ -z "$pass" ]]; then
        echo "✗ Keychain 中未找到 ${name} 的密码（service=${KEYCHAIN_SERVICE}）" >&2
        return 1
    fi
    sshpass -p "$pass" ssh -o StrictHostKeyChecking=no -p "$port" "$target"
}

_define_alias() {
    local name="$1" target="$2" port="$3" method="$4"
    case "$method" in
        ""|key)
            unset -f "$name" 2>/dev/null || true
            eval "alias ${name}='ssh -p ${port} ${target}'"
            ;;
        keychain)
            if ! command -v sshpass &>/dev/null; then
                echo "⚠ ${name} 需要 sshpass: brew install esolitos/ipa/sshpass" >&2
                return 1
            fi
            unalias "$name" 2>/dev/null || true
            eval "${name}() { _ssh_alias_connect '${name}' '${target}' '${port}'; }"
            ;;
        *)
            # 旧版明文密码 —— 保留兼容，提示迁移
            if ! command -v sshpass &>/dev/null; then
                return 1
            fi
            unset -f "$name" 2>/dev/null || true
            eval "alias ${name}='sshpass -p \"${method}\" ssh -o StrictHostKeyChecking=no -p ${port} ${target}'"
            echo "⚠ ${name} 仍为明文密码，建议运行: ssh-alias migrate ${name}" >&2
            ;;
    esac
}

# ========== 子命令 ==========

cmd_add() {
    if [[ $# -lt 2 ]]; then
        echo "用法: ssh-alias add <名称> <用户@主机> [端口]"
        echo "示例: ssh-alias add myserver root@192.168.1.100 22"
        return 1
    fi

    local name="$1" target="$2" port="${3:-22}"

    echo ""
    echo "选择登录方式:"
    echo "  1) SSH 密钥免密登录（推荐）"
    echo "  2) 密码登录（密码加密存储于 macOS Keychain）"
    echo ""
    read -p "请选择 [1/2]: " mode

    # 移除同名旧记录（包括可能残留的 Keychain 条目）
    if [[ -f "$ALIASES_FILE" ]] && grep -q "^${name}|" "$ALIASES_FILE"; then
        sed -i '' "/^${name}|/d" "$ALIASES_FILE"
    fi
    _keychain_delete "$name"

    case "$mode" in
        1)
            if [[ ! -f "$HOME/.ssh/id_rsa.pub" && ! -f "$HOME/.ssh/id_ed25519.pub" ]]; then
                echo "未找到 SSH 密钥，正在生成..."
                ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -N ""
            fi

            echo "正在将公钥拷贝到 ${target}:${port} ..."
            if ssh-copy-id -p "$port" "$target"; then
                echo "${name}|${target}|${port}|key" >> "$ALIASES_FILE"
                _define_alias "$name" "$target" "$port" "key"
                echo "✓ 已添加: ${name} -> ${target}:${port}（密钥免密）"
            else
                echo "✗ 公钥拷贝失败，请检查连接信息"
                return 1
            fi
            ;;
        2)
            if ! _keychain_available; then
                echo "✗ 未找到 macOS security 命令，无法使用 Keychain 存储"
                return 1
            fi
            if ! command -v sshpass &>/dev/null; then
                echo "⚠ 需要先安装 sshpass: brew install esolitos/ipa/sshpass"
                return 1
            fi
            read -s -p "请输入密码: " pass
            echo ""
            _keychain_set "$name" "$pass"
            echo "${name}|${target}|${port}|keychain" >> "$ALIASES_FILE"
            _define_alias "$name" "$target" "$port" "keychain"
            echo "✓ 已添加: ${name} -> ${target}:${port}（密码已加密保存到 Keychain）"
            ;;
        *)
            echo "✗ 无效选择"
            return 1
            ;;
    esac
}

cmd_list() {
    if [[ ! -s "$ALIASES_FILE" ]]; then
        echo "暂无别名。使用 ssh-alias add 添加"
        return
    fi

    printf "%-15s %-30s %-6s %s\n" "名称" "目标" "端口" "方式"
    printf "%-15s %-30s %-6s %s\n" "----" "----" "----" "----"
    while IFS='|' read -r name target port method; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        local label
        case "$method" in
            ""|key)    label="密钥" ;;
            keychain)  label="密码 (Keychain)" ;;
            *)         label="密码 (明文-建议迁移)" ;;
        esac
        printf "%-15s %-30s %-6s %s\n" "$name" "$target" "$port" "$label"
    done < "$ALIASES_FILE"
}

cmd_rm() {
    if [[ -z "$1" ]]; then
        echo "用法: ssh-alias rm <名称>"
        return 1
    fi

    local name="$1"
    if grep -q "^${name}|" "$ALIASES_FILE" 2>/dev/null; then
        sed -i '' "/^${name}|/d" "$ALIASES_FILE"
        _keychain_delete "$name"
        echo "✓ 已删除: ${name}"
    else
        echo "✗ 未找到别名: ${name}"
        return 1
    fi
}

cmd_migrate() {
    if [[ ! -f "$ALIASES_FILE" ]]; then
        echo "无配置文件，无需迁移"
        return 0
    fi
    if ! _keychain_available; then
        echo "✗ 未找到 macOS security 命令，无法迁移"
        return 1
    fi

    local target_name="$1"  # 可选：只迁移指定名称
    local tmp; tmp="$(mktemp)"
    local migrated=0

    while IFS='|' read -r name target port method; do
        if [[ -z "$name" || "$name" == \#* ]]; then
            printf '%s\n' "${name}${target:+|$target}${port:+|$port}${method:+|$method}" >> "$tmp"
            continue
        fi
        # 仅对"非空且不是 key/keychain"的条目迁移
        if [[ -n "$method" && "$method" != "key" && "$method" != "keychain" ]] \
           && [[ -z "$target_name" || "$target_name" == "$name" ]]; then
            _keychain_set "$name" "$method"
            echo "${name}|${target}|${port}|keychain" >> "$tmp"
            migrated=$((migrated + 1))
            echo "✓ 已迁移: $name"
        else
            echo "${name}|${target}|${port}|${method}" >> "$tmp"
        fi
    done < "$ALIASES_FILE"

    mv "$tmp" "$ALIASES_FILE"
    echo "完成，共迁移 ${migrated} 个条目。请运行 ssh-alias reload 生效"
}

cmd_help() {
    cat <<'EOF'
ssh-alias - SSH 快捷登录管理工具

用法:
  ssh-alias add <名称> <用户@主机> [端口]    添加 SSH 别名
  ssh-alias list                             列出所有别名
  ssh-alias rm <名称>                        删除别名（同时清理 Keychain）
  ssh-alias reload                           重新加载到当前 shell
  ssh-alias migrate [名称]                   把旧版明文密码迁移到 Keychain
  ssh-alias help                             显示帮助

示例:
  ssh-alias add myserver root@192.168.1.100 22
  ssh-alias add prod root@10.0.0.1
  myserver                                   直接连接
  ssh-alias list
  ssh-alias rm myserver
  ssh-alias migrate                          迁移所有明文条目

存储:
  别名元信息: ~/.ssh-aliases.conf
  密码:       macOS Keychain (service=ssh-alias)
EOF
}

# ========== 入口 ==========

main() {
    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        add)     cmd_add "$@" ;;
        list|ls) cmd_list ;;
        rm)      cmd_rm "$@" ;;
        reload)  _load_aliases && echo "✓ 已重新加载" ;;
        migrate) cmd_migrate "$@" ;;
        help|--help|-h) cmd_help ;;
        *)
            echo "未知命令: $cmd"
            cmd_help
            return 1
            ;;
    esac
}

# 直接执行才进入 main
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"
