# ssh-alias shell 加载文件
# 由 install.sh 自动 source 到 shell rc 文件中

_ssh_alias_file="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"

# 加载别名到当前 shell
_ssh_alias_load() {
    [[ ! -f "$_ssh_alias_file" ]] && return
    while IFS='|' read -r name target port pass; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        if [[ -n "$pass" ]]; then
            if command -v sshpass &>/dev/null; then
                eval "alias ${name}='sshpass -p \"${pass}\" ssh -o StrictHostKeyChecking=no -p ${port} ${target}'"
            fi
        else
            eval "alias ${name}='ssh -p ${port} ${target}'"
        fi
    done < "$_ssh_alias_file"
}

# ssh-alias 是个 shell 函数，在当前 shell 执行
ssh-alias() {
    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        reload)
            # 清除旧别名
            [[ -f "$_ssh_alias_file" ]] && while IFS='|' read -r name _; do
                [[ -z "$name" || "$name" == \#* ]] && continue
                unalias "$name" 2>/dev/null
            done < "$_ssh_alias_file"
            _ssh_alias_load
            echo "✓ 已重新加载"
            ;;
        add)
            # 调用脚本处理交互，最后重新加载
            bash "$HOME/.local/bin/ssh-alias/ssh-alias.sh" add "$@"
            _ssh_alias_load
            ;;
        list|ls)
            bash "$HOME/.local/bin/ssh-alias/ssh-alias.sh" list
            ;;
        rm)
            bash "$HOME/.local/bin/ssh-alias/ssh-alias.sh" rm "$@"
            unalias "$1" 2>/dev/null
            ;;
        help|--help|-h)
            bash "$HOME/.local/bin/ssh-alias/ssh-alias.sh" help
            ;;
        *)
            echo "未知命令: $cmd"
            bash "$HOME/.local/bin/ssh-alias/ssh-alias.sh" help
            ;;
    esac
}

# 启动时自动加载别名
_ssh_alias_load
