#!/bin/bash
# tools 安装脚本
# 用法:
#   ./install.sh                      # 安装所有工具
#   ./install.sh ssh-alias            # 安装指定工具
#   ./install.sh --uninstall          # 卸载所有工具
#   ./install.sh --uninstall ssh-alias
#   ./install.sh --lang en            # 使用英文输出（目前为 stub，自动回退中文）

# 强制 UTF-8 locale，避免 macOS 自带 bash 3.2 在默认 C locale 下截断中文
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="$REPO_DIR/tools"
INSTALL_DIR="$HOME/.local/bin"
SHELL_RC=""
LANG_CHOICE="cn"

# ========== i18n ==========
# bash 3.2 没有关联数组，用 MSG_<lang>_<key> 命名约定 + indirect expansion。
# 中文为完整版本；英文留 stub（值为空时自动回退到中文）。

# --- 中文（默认） ---
MSG_cn_shell_rc="Shell 配置文件: %s"
MSG_cn_path_added="✓ 已将 %s 添加到 PATH"
MSG_cn_tool_not_found="✗ 未找到工具: %s"
MSG_cn_available_tools="  可用工具:%s"
MSG_cn_cmd_installed="✓ 已安装命令: %s"
MSG_cn_rc_added="✓ 已添加到 %s"
MSG_cn_rc_skipped="- 已存在于 %s，跳过"
MSG_cn_install_done="✓ %s 安装完成"
MSG_cn_dir_removed="✓ 已删除 %s"
MSG_cn_link_removed="✓ 已删除 %s"
MSG_cn_rc_removed="✓ 已从 %s 移除"
MSG_cn_uninstall_done="✓ %s 已卸载"
MSG_cn_reload_hint="执行 source %s 或重新打开终端以生效"
MSG_cn_bad_lang="✗ 不支持的语言: %s（仅支持 cn / en）"

# --- English (stub: 留空 → 自动回退到中文) ---
MSG_en_shell_rc="Shell config: %s"
MSG_en_path_added=""
MSG_en_tool_not_found=""
MSG_en_available_tools=""
MSG_en_cmd_installed=""
MSG_en_rc_added=""
MSG_en_rc_skipped=""
MSG_en_install_done=""
MSG_en_dir_removed=""
MSG_en_link_removed=""
MSG_en_rc_removed=""
MSG_en_uninstall_done=""
MSG_en_reload_hint=""
MSG_en_bad_lang=""

# 取消息模板：先取选定语言，空则回退中文
_msg() {
    local key="$1" fmt
    eval "fmt=\${MSG_${LANG_CHOICE}_${key}}"
    if [[ -z "$fmt" ]]; then
        eval "fmt=\${MSG_cn_${key}}"
    fi
    printf '%s' "$fmt"
}

# 输出一行（自动 i18n + printf 安全处理多字节）
say() {
    local key="$1"; shift
    local fmt; fmt="$(_msg "$key")"
    # 用 -- 防止以 '-' 开头的消息被 printf 当 flag 解析
    # shellcheck disable=SC2059
    printf -- "$fmt\n" "$@"
}

# 同上，输出到 stderr
say_err() {
    local key="$1"; shift
    local fmt; fmt="$(_msg "$key")"
    # shellcheck disable=SC2059
    printf -- "$fmt\n" "$@" >&2
}

# ========== 检测环境 ==========

detect_shell_rc() {
    if [[ -n "$ZSH_VERSION" || -f "$HOME/.zshrc" ]]; then
        SHELL_RC="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" || -f "$HOME/.bashrc" ]]; then
        SHELL_RC="$HOME/.bashrc"
    else
        SHELL_RC="$HOME/.profile"
    fi
    say shell_rc "$SHELL_RC"
}

# ========== 安装单个工具 ==========

install_tool() {
    local tool_name="$1"
    local tool_dir="$TOOLS_DIR/$tool_name"
    local tool_script="$tool_dir/$tool_name.sh"

    if [[ ! -d "$tool_dir" ]]; then
        say tool_not_found "$tool_name"
        say available_tools "$(list_available)"
        return 1
    fi

    mkdir -p "$INSTALL_DIR"

    # 主脚本 → symlink 到 PATH
    if [[ -f "$tool_script" ]]; then
        chmod +x "$tool_script"
        rm -f "$INSTALL_DIR/$tool_name"
        ln -s "$tool_script" "$INSTALL_DIR/$tool_name"
        say cmd_installed "$INSTALL_DIR/$tool_name"
    fi

    # 可选 source.sh → 写入 shell rc
    local source_file="$tool_dir/source.sh"
    if [[ -f "$source_file" ]]; then
        local marker="# >>> tools/$tool_name >>>"
        if ! grep -qF "$marker" "$SHELL_RC" 2>/dev/null; then
            cat >> "$SHELL_RC" <<EOF

$marker
TOOL_DIR="$tool_dir"
source "$source_file"
unset TOOL_DIR
# <<< tools/$tool_name <<<
EOF
            say rc_added "$SHELL_RC"
        else
            say rc_skipped "$SHELL_RC"
        fi
    fi

    say install_done "$tool_name"
}

# ========== 卸载单个工具 ==========

uninstall_tool() {
    local tool_name="$1"
    local target_dir="$INSTALL_DIR/$tool_name"

    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        say dir_removed "$target_dir"
    fi

    if [[ -L "$INSTALL_DIR/$tool_name" ]]; then
        rm -f "$INSTALL_DIR/$tool_name"
        say link_removed "$INSTALL_DIR/$tool_name"
    fi

    local marker_start="# >>> tools/$tool_name >>>"
    local marker_end="# <<< tools/$tool_name <<<"
    if [[ -f "$SHELL_RC" ]] && grep -qF "$marker_start" "$SHELL_RC"; then
        sed -i '' "\|$marker_start|,\|$marker_end|d" "$SHELL_RC"
        say rc_removed "$SHELL_RC"
    fi

    say uninstall_done "$tool_name"
}

# ========== 辅助 ==========

list_available() {
    local tools=""
    for dir in "$TOOLS_DIR"/*/; do
        [[ -d "$dir" ]] || continue
        tools="$tools $(basename "$dir")"
    done
    printf '%s' "$tools"
}

# ========== 主流程 ==========

main() {
    # 解析全局选项（--lang / --uninstall）+ 收集剩余位置参数
    local action="install"
    local positional=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lang)      LANG_CHOICE="$2"; shift 2 ;;
            --lang=*)    LANG_CHOICE="${1#--lang=}"; shift ;;
            --uninstall) action="uninstall"; shift ;;
            --)          shift; positional+=("$@"); break ;;
            *)           positional+=("$1"); shift ;;
        esac
    done

    case "$LANG_CHOICE" in
        cn|en) ;;
        *) say_err bad_lang "$LANG_CHOICE"; exit 1 ;;
    esac

    detect_shell_rc

    # 确保 ~/.local/bin 在 PATH 中
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        local path_marker="# >>> tools PATH >>>"
        if ! grep -qF "$path_marker" "$SHELL_RC" 2>/dev/null; then
            cat >> "$SHELL_RC" <<EOF

$path_marker
export PATH="$INSTALL_DIR:\$PATH"
# <<< tools PATH <<<
EOF
            export PATH="$INSTALL_DIR:$PATH"
            say path_added "$INSTALL_DIR"
        fi
    fi

    if [[ ${#positional[@]} -gt 0 ]]; then
        for tool in "${positional[@]}"; do
            if [[ "$action" == "install" ]]; then
                install_tool "$tool"
            else
                uninstall_tool "$tool"
            fi
        done
    else
        for dir in "$TOOLS_DIR"/*/; do
            [[ -d "$dir" ]] || continue
            local name; name="$(basename "$dir")"
            if [[ "$action" == "install" ]]; then
                install_tool "$name"
            else
                uninstall_tool "$name"
            fi
        done
    fi

    printf '\n'
    say reload_hint "$SHELL_RC"
}

main "$@"
