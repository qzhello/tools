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
```

## 卸载

```bash
./install.sh --uninstall                # 卸载所有
./install.sh --uninstall ssh-alias      # 卸载指定工具
```

## 工具列表

| 工具 | 说明 |
|------|------|
| [ssh-alias](tools/ssh-alias/) | SSH 快捷登录管理，密钥免密 / 密码登录（密码加密存于 macOS Keychain） |

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
