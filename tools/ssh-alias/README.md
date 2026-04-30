# ssh-alias

SSH 快捷登录管理工具，一条命令连接远程服务器。

支持两种登录方式：
- **密钥免密登录**（推荐）：自动检测/生成 SSH 密钥，拷贝公钥到服务器
- **密码登录**：明文存储密码，通过 sshpass 自动登录

## 用法

```bash
ssh-alias add <名称> <用户@主机> [端口]    # 添加别名
ssh-alias list                             # 列出所有别名
ssh-alias rm <名称>                        # 删除别名

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

- macOS / Linux
- [sshpass](https://sourceforge.net/projects/sshpass/)（仅密码登录需要）

```bash
# macOS
brew install esolitos/ipa/sshpass

# Ubuntu/Debian
sudo apt install sshpass
```

## 配置文件

别名存储在 `~/.ssh-aliases.conf`，格式：

```
名称|用户@主机|端口|密码
```

密钥登录的密码字段为空。

## License

MIT
