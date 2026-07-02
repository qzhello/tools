# cmd-alias

常用命令快捷别名工具，shell 入口是一个字母：`a`。

解决两个痛点：

1. **长命令太长**：注册一次，以后 `a cc` 直接执行完整命令
2. **记不住完整命令**：输入 `a <前缀>` 按 **Tab**，行内展开为匹配的完整命令（来源：注册别名 + shell 历史），连按 Tab 循环切换，回车执行

## 用法

```bash
a add <名称> "<完整命令>"    # 注册别名（同名覆盖）
a rm <名称>                  # 删除别名
a list                       # 列出所有别名
a <名称> [额外参数...]       # 执行注册的命令
a help                       # 显示帮助
```

## 示例

```bash
# 注册：以后 a cc 直接启动 claude
a add cc "claude --dangerously-skip-permissions --permission-mode=bypassPermissions"

a cc                # 执行完整命令
a cc --resume       # 额外参数会追加到命令末尾

# Tab 行内展开（zsh）
a claude<Tab>
# → 行内变成: a claude --dangerously-skip-permissions --permission-mode=bypassPermissions
# 再按 Tab   → 循环切换到下一条匹配的历史命令
# 回车       → 执行展开后的真实命令
```

## Tab 展开细节

- 仅当输入行以 `a ` 开头时接管 Tab，其余场景原样交还原有补全（兼容 fzf-tab 等自定义 Tab widget）
- 候选来源与排序：**注册别名优先**，其后是 shell 历史（最近优先、去重、最多 15 条），`a` 自身的调用记录会被排除
- 展开后回车，`a` 函数发现首词不是注册别名时，会把整行当普通命令执行，所以体验上等价于直接运行原命令
- Tab 展开仅支持 **zsh**（macOS 默认 shell）；bash 下 `a cc` / `a add` 等功能不受影响，只是没有 Tab 行内展开

## 存储

`~/.cmd-aliases.conf`，每行格式：

```
名称|完整命令
```

自定义路径：`export CMD_ALIASES_FILE=/path/to/file`

> ⚠️ 注册的命令通过 `eval` 执行，配置文件内容等同于可执行代码，请勿写入不可信内容。

## License

MIT
