# ssh-alias

SSH 快捷登录管理工具，一条命令连接远程服务器。

支持两种登录方式：
- **密钥免密登录**（推荐）：自动检测/生成 SSH 密钥，拷贝公钥到服务器
- **密码登录**：密码加密保存到 **macOS Keychain**，配置文件不存明文，运行时按需取出

## 用法

```bash
ssh-alias add <名称> <用户@主机> [端口]    # 添加别名
ssh-alias list                             # 列出所有别名
ssh-alias rm <名称>                        # 删除别名（同时清理 Keychain）
ssh-alias reload                           # 改完配置后重新加载到当前 shell
ssh-alias migrate [名称]                   # 把旧版明文密码迁移到 Keychain

# 添加后直接用别名登录
myserver
```

## 示例

```bash
# 添加（交互式选择密钥或密码方式）
ssh-alias add myserver root@192.168.1.100 22
ssh-alias add prod root@10.0.0.1

# 登录
myserver
prod

# 管理
ssh-alias list
ssh-alias rm myserver
```

## 依赖

- macOS（密码模式依赖系统自带的 `security` Keychain CLI）
- [sshpass](https://sourceforge.net/projects/sshpass/)（仅密码模式需要）

```bash
# macOS
brew install esolitos/ipa/sshpass
```

> Linux 用户：密钥模式可以正常使用；密码模式目前仅支持 macOS Keychain。

## 存储

- **别名元信息**：`~/.ssh-aliases.conf`，每行格式：

  ```
  名称|用户@主机|端口|方式
  ```

  其中"方式"取值：
  - 空 或 `key`：密钥免密
  - `keychain`：密码存于 macOS Keychain（service=`ssh-alias`，account=别名）

- **密码本身**：从不写入磁盘配置文件，仅存于 Keychain，受系统加密与访问控制保护。每次连接时由 shell 函数调用 `security find-generic-password` 临时取出，传给 `sshpass`。

  自定义 service 名：`export SSH_ALIAS_KEYCHAIN_SERVICE=my-service`

## 从旧版迁移

旧版（v1.0）把密码明文写在 `~/.ssh-aliases.conf` 第 4 段。升级后这些条目仍可用，但每次加载会提示迁移：

```bash
ssh-alias migrate          # 全部迁移
ssh-alias migrate myserver # 只迁某条
ssh-alias reload           # 在当前 shell 生效
```

迁移后配置文件第 4 段会替换为 `keychain`，原始密码进入 Keychain。

## 查看 / 手动清理 Keychain 条目

```bash
security find-generic-password -s ssh-alias -a myserver        # 看条目
security find-generic-password -s ssh-alias -a myserver -w     # 解出密码
security delete-generic-password -s ssh-alias -a myserver      # 删除
```

## License

MIT
