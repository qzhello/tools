#!/bin/bash
# ssh-alias - SSH 快捷登录管理工具
# 支持密钥免密登录和密码登录两种方式

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ALIASES_FILE="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"
VERSION="1.0.0"

# ========== 核心函数 ==========

_load_aliases() {
    [[ ! -f "$ALIASES_FILE" ]] && return
    while IFS='|' read -r name target port pass; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        _define_alias "$name" "$target" "$port" "$pass"
    done < "$ALIASES_FILE"
}

_define_alias() {
    local name="$1" target="$2" port="$3" pass="$4"
    if [[ -n "$pass" ]]; then
        if ! command -v sshpass &>/dev/null; then
            echo "⚠ 需要安装 sshpass: brew install esolitos/ipa/sshpass"
            return 1
        fi
        eval "alias ${name}='sshpass -p \"${pass}\" ssh -o StrictHostKeyChecking=no -p ${port} ${target}'"
    else
        eval "alias ${name}='ssh -p ${port} ${target}'"
    fi
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
    echo "  2) 密码登录（明文存储）"
    echo ""
    read -p "请选择 [1/2]: " mode

    # 移除同名旧记录
    [[ -f "$ALIASES_FILE" ]] && grep -q "^${name}|" "$ALIASES_FILE" && sed -i '' "/^${name}|/d" "$ALIASES_FILE"

    case "$mode" in
        1)
            if [[ ! -f "$HOME/.ssh/id_rsa.pub" && ! -f "$HOME/.ssh/id_ed25519.pub" ]]; then
                echo "未找到 SSH 密钥，正在生成..."
                ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -N ""
            fi

            echo "正在将公钥拷贝到 ${target}:${port} ..."
            if ssh-copy-id -p "$port" "$target"; then
                echo "${name}|${target}|${port}|" >> "$ALIASES_FILE"
                _define_alias "$name" "$target" "$port" ""
                echo "✓ 已添加: ${name} -> ${target}:${port}（密钥免密）"
            else
                echo "✗ 公钥拷贝失败，请检查连接信息"
                return 1
            fi
            ;;
        2)
            read -s -p "请输入密码: " pass
            echo ""
            echo "${name}|${target}|${port}|${pass}" >> "$ALIASES_FILE"
            _define_alias "$name" "$target" "$port" "$pass"
            echo "✓ 已添加: ${name} -> ${target}:${port}（密码登录）"
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
    while IFS='|' read -r name target port pass; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        local method="${pass:+密码}"
        method="${method:-密钥}"
        printf "%-15s %-30s %-6s %s\n" "$name" "$target" "$port" "$method"
    done < "$ALIASES_FILE"
}

cmd_rm() {
    if [[ -z "$1" ]]; then
        echo "用法: ssh-alias rm <名称>"
        return 1
    fi

    local name="$1"
    if grep -q "^${name}|" "$ALIASES_FILE"; then
        sed -i '' "/^${name}|/d" "$ALIASES_FILE"
        unalias "$name" 2>/dev/null
        echo "✓ 已删除: ${name}"
    else
        echo "✗ 未找到别名: ${name}"
        return 1
    fi
}

cmd_reload() {
    # 清除当前会话中已有的别名
    while IFS='|' read -r name target port pass; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        unalias "$name" 2>/dev/null
    done < "$ALIASES_FILE"

    # 重新加载
    _load_aliases
    echo "✓ 已重新加载 $(wc -l < "$ALIASES_FILE" | tr -d ' ') 个别名"
}

cmd_help() {
    cat <<'EOF'
ssh-alias - SSH 快捷登录管理工具

用法:
  ssh-alias add <名称> <用户@主机> [端口]    添加 SSH 别名
  ssh-alias list                             列出所有别名
  ssh-alias rm <名称>                        删除别名
  ssh-alias reload                           重新加载配置文件
  ssh-alias help                             显示帮助

示例:
  ssh-alias add myserver root@192.168.1.100 22
  ssh-alias add prod root@10.0.0.1
  myserver                                   直接连接
  ssh-alias list                             查看所有
  ssh-alias rm myserver                      删除
  ssh-alias reload                           改完配置后重新加载

配置文件: ~/.ssh-aliases.conf
EOF
}

# ========== 入口 ==========

main() {
    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        add)    cmd_add "$@" ;;
        list|ls) cmd_list ;;
        rm)     cmd_rm "$@" ;;
        reload) _load_aliases && echo "✓ 已重新加载" ;;
        help|--help|-h) cmd_help ;;
        *)
            echo "未知命令: $cmd"
            cmd_help
            return 1
            ;;
    esac
}

# 加载已有别名
_load_aliases

# 支持 source 方式（加载别名）和子命令方式
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"
