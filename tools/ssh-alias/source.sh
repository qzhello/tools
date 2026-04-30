# ssh-alias shell 加载文件
# 由 install.sh 自动 source 到 shell rc 文件中

TOOLS_DIR="$HOME/.local/bin/ssh-alias"

if [[ -f "$TOOLS_DIR/ssh-alias.sh" ]]; then
    # 仅加载别名定义（不执行入口函数）
    _load_ssh_aliases() {
        local aliases_file="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"
        [[ ! -f "$aliases_file" ]] && return
        while IFS='|' read -r name target port pass; do
            [[ -z "$name" || "$name" == \#* ]] && continue
            if [[ -n "$pass" ]]; then
                if command -v sshpass &>/dev/null; then
                    eval "alias ${name}='sshpass -p \"${pass}\" ssh -o StrictHostKeyChecking=no -p ${port} ${target}'"
                fi
            else
                eval "alias ${name}='ssh -p ${port} ${target}'"
            fi
        done < "$aliases_file"
    }
    _load_ssh_aliases
    unset -f _load_ssh_aliases
fi
