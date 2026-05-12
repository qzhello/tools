# tools

**中文** | [English](README.en.md)

日常小工具集，一个工具一个目录，统一安装，即装即用。

## 平台支持

- ✅ **macOS**：完整支持（开发主平台）
- ✅ **Linux**：基本支持，部分工具的密码模式（依赖 macOS Keychain）不可用
- ❌ **Windows**：不支持。如需使用，请在 WSL2 内按 Linux 方式安装

## 前置依赖

所有工具都用 **Python 3.9+** 编写（部分用到 `zoneinfo`、`dataclasses` 等特性），bash 只做环境处理。除此之外，少数工具会调用系统命令。

### Python

需要 **Python 3.9 或更高版本**。

```bash
python3 --version    # 检查；< 3.9 请升级
```

| 平台 | 安装方式 |
|------|----------|
| macOS（推荐） | `brew install python@3.12` |
| macOS（自带）| 系统已带 `python3`，但版本可能较老（< 3.9 时部分工具异常）|
| Ubuntu/Debian | `sudo apt install python3 python3-venv` |
| Fedora/CentOS | `sudo dnf install python3` |

### 系统命令

| 工具 | 依赖的系统命令 | macOS | Linux 安装 |
|------|---------------|-------|-----------|
| ssh-alias | `ssh`, `security`(Keychain) | 自带 | `apt install openssh-client`（密码模式不可用：依赖 macOS Keychain） |
| jsonx     | `pbcopy`/`pbpaste`           | 自带 | 剪贴板模式不可用 |
| datex     | （无；剪贴板模式需 `pbpaste`） | 自带 | 剪贴板模式不可用 |
| pingx     | `ping`                       | 自带 | 自带       |
| tracex    | `traceroute`                 | 自带 | `apt install traceroute` |
| dnsx      | `dig`                        | 自带 | `apt install dnsutils` |
| portx     | `lsof`                       | 自带 | `apt install lsof` |
| sizex     | （无）                       | -     | -          |
| procx     | `ps`                         | 自带 | 自带       |
| certx     | `openssl`                    | 自带 | `apt install openssl` |
| base64x   | `pbcopy`/`pbpaste`（仅剪贴板模式）| 自带 | 剪贴板模式需 `xclip` 或 `wl-copy`（当前仅 macOS 支持） |
| topx      | `top`, `ps`, `netstat`, `iostat` | 自带 | `apt install net-tools sysstat` |
| ipx       | `ifconfig`, `route`/`ip`, `scutil`（mac） | 自带 | `apt install net-tools iproute2` |
| pathx     | （无）                       | -     | -          |
| loadx     | `top`, `vm_stat`, `pmset`, `iostat`, `netstat`, `ioreg`（mac） | 自带 | mac 专用 |
| aix       | （无；读 `~/.claude/projects/`） | -     | -          |

### 一键安装前置（参考）

**macOS**（系统都自带，只需要 Python）：

```bash
# 已有 brew 时
brew install python@3.12
```

**Ubuntu / Debian**：

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv \
    openssh-client openssl \
    iproute2 net-tools dnsutils sysstat \
    lsof traceroute iputils-ping
```

**Fedora / CentOS / RHEL**：

```bash
sudo dnf install -y \
    python3 \
    openssh-clients openssl \
    net-tools bind-utils sysstat \
    lsof traceroute iputils
```

## 安装

```bash
git clone https://github.com/qzhello/tools.git
cd tools
./install.sh                    # 安装所有工具
./install.sh ssh-alias jsonx    # 安装指定工具
./install.sh --lang en jsonx    # 指定输出语言（默认 cn）
```

会自动：

1. 把每个工具的命令软链到 `~/.local/bin/<tool>`
2. 把 `~/.local/bin` 加入你的 `PATH`（写入 `~/.zshrc` 或 `~/.bashrc`）
3. 有 `source.sh` 的工具（如 `ssh-alias`）追加 source 行到 shell rc

安装后执行 `source ~/.zshrc`（或重开终端）生效。

## 常用命令

```bash
./install.sh list                       # 列出所有工具及安装状态
./install.sh --help                     # 完整帮助
./install.sh <tool> [<tool> ...]        # 安装一个或多个工具
./install.sh --uninstall                # 卸载所有
./install.sh --uninstall <tool>         # 卸载指定工具
```

`./install.sh list` 输出示例：

```
可用工具（共 12 个，已安装 9）

✓ base64x    base64 双向自动识别，支持 url-safe / 文件 / 剪贴板进出
✓ certx      HTTPS 证书检查，到期天数 + SAN + 链 + TLS 版本
- dnsx       多 resolver DNS 对比查询，差异高亮（CDN/污染/未生效排查）
✓ datex      时间戳 ↔ 日期双向转换，自动识别 10/13/16/19 位时间戳
...

✓ 已安装   - 未安装
```

## 语言支持

`install.sh` 支持 `--lang cn|en`，默认 `cn`：

- 中文：完整翻译
- 英文：仅留出框架（`MSG_en_*` 变量），翻译为空时自动回退到中文
- 其他语言：报错退出

要补全英文翻译，编辑 `install.sh` 顶部的 `MSG_en_*` 变量即可。

## 工具列表

| 工具 | 说明 |
|------|------|
| [ssh-alias](tools/ssh-alias/) | SSH 快捷登录管理，密钥免密 / 密码登录（密码加密存于 macOS Keychain） |
| [jsonx](tools/jsonx/)         | JSON 美化，结果同时打到 stdout 和剪贴板，支持参数 / 管道 / 剪贴板 / 文件 / 目录 |
| [datex](tools/datex/)         | 时间戳 ↔ 日期双向转换，自动识别 10/13/16/19 位时间戳，一次输出多种格式 |
| [pingx](tools/pingx/)         | 实时可视化 ping，sparkline 折线 + 丢包率 + min/avg/p95/max 统计 |
| [tracex](tools/tracex/)       | 可视化路由追踪（mtr 风格），按跳显示丢包率 + 延迟 sparkline |
| [dnsx](tools/dnsx/)           | 多 DNS resolver 并行查询对比，差异高亮，排查 CDN/污染/未生效 |
| [portx](tools/portx/)         | 列出本机监听端口 + 进程，识别常见服务，支持 `-k` 杀进程 |
| [sizex](tools/sizex/)         | 目录大小可视化，条形图，按大小排序，找谁吃了硬盘 |
| [procx](tools/procx/)         | 进程查看器，按 CPU/内存排序，颜色高亮，支持进程树和 `-k` 杀进程 |
| [certx](tools/certx/)         | HTTPS 证书检查，到期天数高亮，SAN/链/TLS 版本一览 |
| [base64x](tools/base64x/)     | base64 双向自动识别，支持 url-safe、文件、剪贴板进出 |
| [topx](tools/topx/)           | 简洁的系统监控 TUI，4 象限（CPU/MEM/NET/DISK）+ 进程列表，单键交互 |
| [ipx](tools/ipx/)             | 多源公网 IP + ISP/地理位置对比，本机网卡 v4/v6、默认网关、DNS 一览 |
| [pathx](tools/pathx/)         | $PATH 可视化诊断：每项状态/binary 数/来源，重复 + 不存在 + 遮蔽检测，按名查找 |
| [loadx](tools/loadx/)         | 一句话告诉你机器累在哪：CPU/内存/网络/磁盘/电池 各项状态 + Top 消耗者 + 建议 |
| [aix](tools/aix/)             | Claude Code + Codex token 用量统计，TUI 交互，按天/模型/项目/会话/源聚合 |

## 如何添加新工具

1. 在 `tools/` 下新建目录，例如 `tools/my-tool/`
2. 创建主脚本 `tools/my-tool/my-tool.sh`（chmod +x），第二行写一句话描述：`# my-tool - 描述...`
3. 如果需要 shell 启动时自动加载，创建 `tools/my-tool/source.sh`
4. 运行 `./install.sh my-tool` 即可安装

目录结构：

```
tools/
├── install.sh              # 统一安装脚本
├── README.md
├── LICENSE
└── tools/
    ├── ssh-alias/
    │   ├── ssh-alias.sh    # 主命令
    │   ├── source.sh       # shell 启动加载（可选）
    │   └── README.md       # 工具说明
    └── my-tool/
        ├── my-tool.sh
        └── README.md
```

## License

MIT
