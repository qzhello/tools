# ssh-alias shell 加载文件
# 由 install.sh 自动 source 到 shell rc 文件中

_ssh_alias_file="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"
_ssh_alias_script="${TOOL_DIR:-$HOME/.local/bin/ssh-alias}/ssh-alias.sh"
_ssh_alias_keychain_service="${SSH_ALIAS_KEYCHAIN_SERVICE:-ssh-alias}"

# 运行时从 Keychain 取密码并连接
_ssh_alias_connect() {
    local name="$1" target="$2" port="$3"
    local pass
    pass="$(security find-generic-password -s "$_ssh_alias_keychain_service" -a "$name" -w 2>/dev/null)"
    if [[ -z "$pass" ]]; then
        echo "✗ Keychain 中未找到 ${name} 的密码" >&2
        return 1
    fi
    sshpass -p "$pass" ssh -o StrictHostKeyChecking=no -p "$port" "$target"
}

_ssh_alias_define() {
    local name="$1" target="$2" port="$3" method="$4"
    case "$method" in
        ""|key)
            unset -f "$name" 2>/dev/null || true
            eval "alias ${name}='ssh -p ${port} ${target}'"
            ;;
        keychain)
            command -v sshpass &>/dev/null || return 0
            unalias "$name" 2>/dev/null || true
            eval "${name}() { _ssh_alias_connect '${name}' '${target}' '${port}'; }"
            ;;
        *)
            command -v sshpass &>/dev/null || return 0
            unset -f "$name" 2>/dev/null || true
            eval "alias ${name}='sshpass -p \"${method}\" ssh -o StrictHostKeyChecking=no -p ${port} ${target}'"
            ;;
    esac
}

# 加载别名到当前 shell
_ssh_alias_load() {
    [[ ! -f "$_ssh_alias_file" ]] && return
    while IFS='|' read -r name target port method; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        _ssh_alias_define "$name" "$target" "$port" "$method"
    done < "$_ssh_alias_file"
}

# 清除当前 shell 中由本工具创建的别名/函数
_ssh_alias_clear() {
    [[ ! -f "$_ssh_alias_file" ]] && return
    while IFS='|' read -r name _; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        unalias "$name" 2>/dev/null || true
        unset -f "$name" 2>/dev/null || true
    done < "$_ssh_alias_file"
}

# ssh-alias 是个 shell 函数，在当前 shell 执行
ssh-alias() {
    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        reload)
            _ssh_alias_clear
            _ssh_alias_load
            echo "✓ 已重新加载"
            ;;
        add)
            bash "$_ssh_alias_script" add "$@"
            _ssh_alias_clear
            _ssh_alias_load
            ;;
        list|ls)
            bash "$_ssh_alias_script" list
            ;;
        rm)
            local name="$1"
            bash "$_ssh_alias_script" rm "$@"
            [[ -n "$name" ]] && { unalias "$name" 2>/dev/null || true; unset -f "$name" 2>/dev/null || true; }
            ;;
        migrate)
            bash "$_ssh_alias_script" migrate "$@"
            _ssh_alias_clear
            _ssh_alias_load
            ;;
        help|--help|-h)
            bash "$_ssh_alias_script" help
            ;;
        *)
            echo "未知命令: $cmd"
            bash "$_ssh_alias_script" help
            ;;
    esac
}

# 启动时自动加载别名
_ssh_alias_load
