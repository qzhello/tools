# cmd-alias shell 加载文件
# 由 install.sh 自动 source 到 shell rc 文件中
#
# 提供:
#   a <别名> [参数...]     执行注册的命令（如 a cc）
#   a add/rm/list/help     管理别名
#   Tab（仅 zsh）          输入 "a <前缀>" 后按 Tab，行内展开匹配的
#                          注册别名 / 历史命令，连按 Tab 循环切换

_cmd_alias_file="${CMD_ALIASES_FILE:-$HOME/.cmd-aliases.conf}"
_cmd_alias_script="${TOOL_DIR:-$HOME/.local/bin/cmd-alias}/cmd-alias.sh"

# 查找别名对应的完整命令
_cmd_alias_lookup() {
    local name="$1" line
    [[ -f "$_cmd_alias_file" ]] || return 1
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "${line%%|*}" == "$name" ]]; then
            printf '%s' "${line#*|}"
            return 0
        fi
    done < "$_cmd_alias_file"
    return 1
}

# a 是个 shell 函数：管理子命令走脚本，其余在当前 shell 执行
a() {
    local first="${1:-help}"
    case "$first" in
        add|rm|list|ls|help|--help|-h)
            bash "$_cmd_alias_script" "$@"
            ;;
        *)
            local cmd
            if cmd="$(_cmd_alias_lookup "$first")"; then
                shift
                if [[ $# -gt 0 ]]; then
                    eval "$cmd"' "$@"'
                else
                    eval "$cmd"
                fi
            else
                # 非注册别名：整行当普通命令执行（Tab 展开后回车的场景）
                "$@"
            fi
            ;;
    esac
}

# ========== Tab 行内展开（仅 zsh） ==========
if [[ -n "$ZSH_VERSION" ]]; then

typeset -ga _cmd_alias_matches
typeset -g  _cmd_alias_index=0
typeset -g  _cmd_alias_last_buffer=""

# 记录接管前的 Tab widget，非 "a " 场景原样交还（兼容 fzf-tab 等）
typeset -g _cmd_alias_orig_tab
_cmd_alias_orig_tab="${$(bindkey '^I')[(w)2]}"
if [[ -z "$_cmd_alias_orig_tab" || "$_cmd_alias_orig_tab" == "undefined-key" \
      || "$_cmd_alias_orig_tab" == "_cmd_alias_tab" ]]; then
    _cmd_alias_orig_tab="expand-or-complete"
fi

# 收集候选：① 注册别名的完整命令 ② shell 历史（最近优先、去重）
_cmd_alias_collect() {
    local q="$1" line cmd h
    local -a results hist

    if [[ -f "$_cmd_alias_file" ]]; then
        while IFS= read -r line; do
            [[ -z "$line" || "$line" == \#* ]] && continue
            cmd="${line#*|}"
            [[ "$cmd" == "$q"* && "$cmd" != "$q" ]] && results+=("$cmd")
        done < "$_cmd_alias_file"
    fi

    hist=(${(f)"$(fc -lnr 1 2>/dev/null)"})
    for h in "${hist[@]}"; do
        h="${h#"${h%%[![:space:]]*}"}"
        [[ "$h" == "$q"* && "$h" != "$q" ]] || continue
        [[ "$h" == "a" || "$h" == "a "* ]] && continue
        (( ${results[(Ie)$h]} )) && continue
        results+=("$h")
        (( ${#results[@]} >= 15 )) && break
    done

    _cmd_alias_matches=("${results[@]}")
}

_cmd_alias_tab() {
    if [[ "$BUFFER" != "a "* ]]; then
        zle "$_cmd_alias_orig_tab"
        return
    fi

    if [[ -n "$BUFFER" && "$BUFFER" == "$_cmd_alias_last_buffer" \
          && ${#_cmd_alias_matches[@]} -gt 0 ]]; then
        # 连按 Tab：循环切换下一条候选
        (( _cmd_alias_index = _cmd_alias_index % ${#_cmd_alias_matches[@]} + 1 ))
    else
        _cmd_alias_collect "${BUFFER#a }"
        if (( ${#_cmd_alias_matches[@]} == 0 )); then
            zle "$_cmd_alias_orig_tab"
            return
        fi
        _cmd_alias_index=1
    fi

    BUFFER="a ${_cmd_alias_matches[$_cmd_alias_index]}"
    CURSOR=${#BUFFER}
    _cmd_alias_last_buffer="$BUFFER"
}

zle -N _cmd_alias_tab
bindkey '^I' _cmd_alias_tab

fi
