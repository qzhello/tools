# ssh-alias shell 加载文件
# 由 install.sh 自动 source 到 shell rc 文件中

_ssh_alias_file="${SSH_ALIASES_FILE:-$HOME/.ssh-aliases.conf}"
_ssh_alias_script="${TOOL_DIR:-$HOME/.local/bin/ssh-alias}/ssh-alias.sh"
_ssh_alias_keychain_service="${SSH_ALIAS_KEYCHAIN_SERVICE:-ssh-alias}"

# ControlMaster 连接复用：首次认证后，窗口期内的连接不再触发密码 / 2FA
# 字符串版用于 alias 文本，数组版用于函数内直接传参（zsh 不对未加引号的变量分词）
_ssh_alias_persist="${SSH_ALIAS_CONTROL_PERSIST:-8h}"
_ssh_alias_cm_opts="-o ControlMaster=auto -o ControlPath=~/.ssh/ssh-alias-%r@%h-%p -o ControlPersist=${_ssh_alias_persist}"
_ssh_alias_cm_args=(-o ControlMaster=auto -o "ControlPath=~/.ssh/ssh-alias-%r@%h-%p" -o "ControlPersist=${_ssh_alias_persist}")

_ssh_alias_keychain_get() {
    security find-generic-password -s "$_ssh_alias_keychain_service" -a "$1" -w 2>/dev/null
}

# master 连接是否仍存活
_ssh_alias_master_alive() {
    ssh -o "ControlPath=~/.ssh/ssh-alias-%r@%h-%p" -p "$2" -O check "$1" &>/dev/null
}

# 运行时从 Keychain 取密码并连接
_ssh_alias_connect() {
    local name="$1" target="$2" port="$3"
    local pass
    pass="$(_ssh_alias_keychain_get "$name")"
    if [[ -z "$pass" ]]; then
        echo "✗ Keychain 中未找到 ${name} 的密码" >&2
        return 1
    fi
    sshpass -p "$pass" ssh -o StrictHostKeyChecking=no "${_ssh_alias_cm_args[@]}" -p "$port" "$target"
}

# 密码 + TOTP 两步验证自动登录
_ssh_alias_connect_totp() {
    local name="$1" target="$2" port="$3"

    # 复用存活的 master 连接，跳过 2FA
    if _ssh_alias_master_alive "$target" "$port"; then
        ssh "${_ssh_alias_cm_args[@]}" -p "$port" "$target"
        return
    fi

    local pass secret code
    pass="$(_ssh_alias_keychain_get "$name")"
    secret="$(_ssh_alias_keychain_get "${name}.totp")"
    if [[ -z "$pass" || -z "$secret" ]]; then
        echo "✗ Keychain 中未找到 ${name} 的密码或 TOTP 种子" >&2
        return 1
    fi
    if ! code="$(oathtool --totp -b "$secret" 2>/dev/null)"; then
        echo "✗ TOTP 验证码生成失败" >&2
        return 1
    fi

    # expect 脚本必须走临时文件而非 stdin heredoc：
    # interact 需要 stdin 是终端，heredoc 会让它读到 EOF 而瞬间退出
    local exp_script rc=0
    exp_script="$(mktemp)"
    cat > "$exp_script" <<'EXPECT_EOF'
set timeout 25
spawn ssh -o StrictHostKeyChecking=no \
    -o ControlMaster=auto \
    -o ControlPath=~/.ssh/ssh-alias-%r@%h-%p \
    -o ControlPersist=$env(SSH_ALIAS_PERSIST) \
    -p $env(SSH_ALIAS_PORT) $env(SSH_ALIAS_TARGET)
expect {
    -re {(?i)(verification code|one-time|otp|mfa|2fa|totp)[^:\n]*:} {
        send -- "$env(SSH_ALIAS_CODE)\r"
    }
    -re {(?i)password[^:\n]*:} {
        send -- "$env(SSH_ALIAS_PASS)\r"
        exp_continue
    }
    timeout {}
}
interact
EXPECT_EOF
    SSH_ALIAS_PASS="$pass" SSH_ALIAS_CODE="$code" \
    SSH_ALIAS_TARGET="$target" SSH_ALIAS_PORT="$port" \
    SSH_ALIAS_PERSIST="$_ssh_alias_persist" \
    expect -f "$exp_script" || rc=$?
    rm -f "$exp_script"
    return $rc
}

_ssh_alias_define() {
    local name="$1" target="$2" port="$3" method="$4"
    case "$method" in
        ""|key)
            unset -f "$name" 2>/dev/null || true
            eval "alias ${name}='ssh ${_ssh_alias_cm_opts} -p ${port} ${target}'"
            ;;
        keychain)
            command -v sshpass &>/dev/null || return 0
            unalias "$name" 2>/dev/null || true
            eval "${name}() { _ssh_alias_connect '${name}' '${target}' '${port}'; }"
            ;;
        totp)
            { command -v oathtool && command -v expect; } &>/dev/null || return 0
            unalias "$name" 2>/dev/null || true
            eval "${name}() { _ssh_alias_connect_totp '${name}' '${target}' '${port}'; }"
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
