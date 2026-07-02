# ssh-alias

SSH 快捷登录管理工具，一条命令连接远程服务器。

支持三种登录方式：
- **密钥免密登录**（推荐）：自动检测/生成 SSH 密钥，拷贝公钥到服务器
- **密码登录**：密码加密保存到 **macOS Keychain**，配置文件不存明文，运行时按需取出
- **密码 + TOTP 两步验证自动登录**：密码和 TOTP 种子均存 Keychain，连接时用 `oathtool` 实时算出验证码、`expect` 自动应答两个提示，2FA 服务器也能一条命令登录

所有方式均启用 **SSH ControlMaster 连接复用**：首次认证后 8 小时内的连接（含 `scp`/`rsync`）直接复用已有通道，不再触发密码 / 2FA 提示。

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

## 2FA（两步验证）服务器

`ssh-alias add` 时选择方式 3，除密码外还需输入 **TOTP 种子** —— 即服务器绑定 Google Authenticator 等验证器 App 时展示的那串 base32 字符串（形如 `JBSWY3DPEHPK3PXP`，通常在二维码下方可复制）。添加时会现场算一枚验证码供你与 App 对照，防止种子录错。

连接流程：

1. 若 ControlMaster 通道仍存活 → 直接复用，零认证
2. 否则 `oathtool --totp -b <种子>` 实时算码，`expect` 依次应答 `password:` 和 `Verification code:` 提示，随后交还终端交互

> ⚠️ **安全权衡**：TOTP 种子与密码存在同一台机器的 Keychain 中，"两个因素"实际都落在本机——这是用安全性换便利。若不想这样，可选方式 2（密码自动填、验证码手输），配合连接复用，每 8 小时也只需输一次验证码。
>
> 若服务器先要验证码、后要密码（少见顺序），expect 会在应答验证码后交还终端，密码手输即可。

自定义复用窗口：`export SSH_ALIAS_CONTROL_PERSIST=4h`（默认 `8h`）

## 依赖

- macOS（密码/TOTP 模式依赖系统自带的 `security` Keychain CLI）
- [sshpass](https://sourceforge.net/projects/sshpass/)（仅密码模式需要）
- [oath-toolkit](https://www.nongnu.org/oath-toolkit/)（仅 TOTP 模式需要；`expect` 为 macOS 自带）

```bash
# macOS
brew install esolitos/ipa/sshpass    # 密码模式
brew install oath-toolkit            # TOTP 模式
```

> Linux 用户：密钥模式可以正常使用；密码/TOTP 模式目前仅支持 macOS Keychain。

## 存储

- **别名元信息**：`~/.ssh-aliases.conf`，每行格式：

  ```
  名称|用户@主机|端口|方式
  ```

  其中"方式"取值：
  - 空 或 `key`：密钥免密
  - `keychain`：密码存于 macOS Keychain（service=`ssh-alias`，account=别名）
  - `totp`：密码 + TOTP 种子均存于 Keychain（account 分别为 `别名` 和 `别名.totp`）

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
