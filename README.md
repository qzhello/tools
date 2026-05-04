# tools

日常小工具集，一个工具一个目录，统一安装，即装即用。

## 平台支持

- ✅ **macOS**：完整支持（开发主平台）
- ✅ **Linux**：基本支持，部分工具的密码模式（依赖 macOS Keychain）不可用
- ❌ **Windows**：不支持。如需使用，请在 WSL2 内按 Linux 方式安装

## 安装

```bash
git clone https://github.com/qzhello/tools.git
cd tools
./install.sh                    # 安装所有工具
./install.sh ssh-alias          # 只安装指定工具
./install.sh --lang en json     # 指定输出语言（默认 cn；en 目前为 stub，未译条目自动回退中文）
```

## 卸载

```bash
./install.sh --uninstall                # 卸载所有
./install.sh --uninstall ssh-alias      # 卸载指定工具
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
| [json](tools/json/)           | JSON 美化，结果同时打到 stdout 和剪贴板，支持参数 / 管道 / 剪贴板 / 文件 / 目录 |
| [epoch](tools/epoch/)         | 时间戳 ↔ 日期双向转换，自动识别 10/13/16/19 位时间戳，一次输出多种格式 |
| [pingx](tools/pingx/)         | 实时可视化 ping，sparkline 折线 + 丢包率 + min/avg/p95/max 统计 |
| [tracex](tools/tracex/)       | 可视化路由追踪（mtr 风格），按跳显示丢包率 + 延迟 sparkline |
| [dnsx](tools/dnsx/)           | 多 DNS resolver 并行查询对比，差异高亮，排查 CDN/污染/未生效 |
| [ports](tools/ports/)         | 列出本机监听端口 + 进程，识别常见服务，支持 `-k` 杀进程 |
| [sizex](tools/sizex/)         | 目录大小可视化，条形图，按大小排序，找谁吃了硬盘 |
| [procx](tools/procx/)         | 进程查看器，按 CPU/内存排序，颜色高亮，支持进程树和 `-k` 杀进程 |
| [certx](tools/certx/)         | HTTPS 证书检查，到期天数高亮，SAN/链/TLS 版本一览 |
| [b64](tools/b64/)             | base64 双向自动识别，支持 url-safe、文件、剪贴板进出 |

## 如何添加新工具

1. 在 `tools/` 下新建目录，例如 `tools/my-tool/`
2. 创建主脚本 `tools/my-tool/my-tool.sh`（chmod +x）
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
