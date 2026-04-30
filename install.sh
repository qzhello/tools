#!/bin/bash
# tools 安装脚本
# 用法:
#   ./install.sh                    # 安装所有工具
#   ./install.sh ssh-alias          # 安装指定工具
#   ./install.sh --uninstall        # 卸载所有工具
#   ./install.sh --uninstall ssh-alias

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="$REPO_DIR/tools"
INSTALL_DIR="$HOME/.local/bin"
SHELL_RC=""

# ========== 检测环境 ==========

detect_shell_rc() {
    if [[ -n "$ZSH_VERSION" || -f "$HOME/.zshrc" ]]; then
        SHELL_RC="$HOME/.zshrc"
    elif [[ -n "$BASH_VERSION" || -f "$HOME/.bashrc" ]]; then
        SHELL_RC="$HOME/.bashrc"
    else
        SHELL_RC="$HOME/.profile"
    fi
    echo "Shell 配置文件: $SHELL_RC"
}

# ========== 安装单个工具 ==========

install_tool() {
    local tool_name="$1"
    local tool_dir="$TOOLS_DIR/$tool_name"
    local tool_script="$tool_dir/$tool_name.sh"

    if [[ ! -d "$tool_dir" ]]; then
        echo "✗ 未找到工具: $tool_name"
        echo "  可用工具: $(list_available)"
        return 1
    fi

    # 创建安装目录
    mkdir -p "$INSTALL_DIR"

    # 复制工具目录到安装目录
    local target_dir="$INSTALL_DIR/$tool_name"
    mkdir -p "$target_dir"
    cp -r "$tool_dir"/* "$target_dir/"

    # 如果有主脚本，创建符号链接到 PATH
    if [[ -f "$tool_script" ]]; then
        chmod +x "$tool_script"
        ln -sf "$tool_script" "$INSTALL_DIR/$tool_name"
        echo "✓ 已安装命令: $INSTALL_DIR/$tool_name"
    fi

    # 如果工具目录有 shell-source 文件，source 到 rc 文件
    local source_file="$tool_dir/source.sh"
    if [[ -f "$source_file" ]]; then
        local marker="# >>> tools/$tool_name >>>"
        if ! grep -qF "$marker" "$SHELL_RC"; then
            cat >> "$SHELL_RC" <<EOF

$marker
source "$source_file"
# <<< tools/$tool_name <<<
EOF
            echo "✓ 已添加到 $SHELL_RC"
        else
            echo "- 已存在于 $SHELL_RC，跳过"
        fi
    fi

    echo "✓ $tool_name 安装完成"
}

# ========== 卸载单个工具 ==========

uninstall_tool() {
    local tool_name="$1"
    local target_dir="$INSTALL_DIR/$tool_name"

    # 删除安装目录
    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        echo "✓ 已删除 $target_dir"
    fi

    # 删除符号链接
    if [[ -L "$INSTALL_DIR/$tool_name" ]]; then
        rm -f "$INSTALL_DIR/$tool_name"
        echo "✓ 已删除 $INSTALL_DIR/$tool_name"
    fi

    # 从 rc 文件移除 source 行
    local marker_start="# >>> tools/$tool_name >>>"
    local marker_end="# <<< tools/$tool_name <<<"
    if grep -qF "$marker_start" "$SHELL_RC"; then
        sed -i '' "/$marker_start/,/$marker_end/d" "$SHELL_RC"
        echo "✓ 已从 $SHELL_RC 移除"
    fi

    echo "✓ $tool_name 已卸载"
}

# ========== 辅助函数 ==========

list_available() {
    local tools=""
    for dir in "$TOOLS_DIR"/*/; do
        [[ -d "$dir" ]] || continue
        local name="$(basename "$dir")"
        tools="$tools $name"
    done
    echo "$tools"
}

# ========== 主流程 ==========

main() {
    detect_shell_rc

    local action="install"
    [[ "$1" == "--uninstall" ]] && action="uninstall" && shift

    # 确保 ~/.local/bin 在 PATH 中
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        local path_marker="# >>> tools PATH >>>"
        if ! grep -qF "$path_marker" "$SHELL_RC"; then
            cat >> "$SHELL_RC" <<EOF

$path_marker
export PATH="$INSTALL_DIR:\$PATH"
# <<< tools PATH <<<
EOF
            export PATH="$INSTALL_DIR:$PATH"
            echo "✓ 已将 $INSTALL_DIR 添加到 PATH"
        fi
    fi

    if [[ -n "$1" ]]; then
        # 安装/卸载指定工具
        for tool in "$@"; do
            if [[ "$action" == "install" ]]; then
                install_tool "$tool"
            else
                uninstall_tool "$tool"
            fi
        done
    else
        # 安装/卸载所有工具
        for dir in "$TOOLS_DIR"/*/; do
            [[ -d "$dir" ]] || continue
            local name="$(basename "$dir")"
            if [[ "$action" == "install" ]]; then
                install_tool "$name"
            else
                uninstall_tool "$name"
            fi
        done
    fi

    echo ""
    echo "执行 source $SHELL_RC 或重新打开终端以生效"
}

main "$@"
