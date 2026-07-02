# tools

[中文](README.md) | **English**

A collection of small daily utilities — one tool per directory, unified install, ready to use.

## Platform Support

- ✅ **macOS**: Full support (primary development platform)
- ✅ **Linux**: Basic support; some tools' password mode (depends on macOS Keychain) is unavailable
- ❌ **Windows**: Not supported. Use WSL2 and install as Linux

## Prerequisites

All tools are written in **Python 3.9+** (using features like `zoneinfo`, `dataclasses`); bash is only used for environment handling. A few tools also call system commands.

### Python

Requires **Python 3.9 or higher**.

```bash
python3 --version    # check; upgrade if < 3.9
```

| Platform | Install |
|----------|---------|
| macOS (recommended) | `brew install python@3.12` |
| macOS (built-in) | System ships `python3`, but version may be old (< 3.9 breaks some tools) |
| Ubuntu/Debian | `sudo apt install python3 python3-venv` |
| Fedora/CentOS | `sudo dnf install python3` |

### System Commands

| Tool | Required Commands | macOS | Linux Install |
|------|------------------|-------|---------------|
| ssh-alias | `ssh`, `security` (Keychain); TOTP mode needs `oathtool`+`expect` | built-in (oathtool: `brew install oath-toolkit`) | `apt install openssh-client` (password/TOTP modes unavailable: depend on macOS Keychain) |
| cmd-alias | (none; Tab expansion requires zsh) | built-in | `a` function works, Tab expansion requires zsh |
| jsonx     | `pbcopy`/`pbpaste`           | built-in | clipboard mode unavailable |
| datex     | (none; clipboard mode needs `pbpaste`) | built-in | clipboard mode unavailable |
| pingx     | `ping`                       | built-in | built-in |
| tracex    | `traceroute`                 | built-in | `apt install traceroute` |
| dnsx      | `dig`                        | built-in | `apt install dnsutils` |
| portx     | `lsof`                       | built-in | `apt install lsof` |
| sizex     | (none)                       | -     | -          |
| procx     | `ps`                         | built-in | built-in |
| certx     | `openssl`                    | built-in | `apt install openssl` |
| base64x   | `pbcopy`/`pbpaste` (clipboard mode only) | built-in | clipboard mode needs `xclip` or `wl-copy` (currently macOS only) |
| topx      | `top`, `ps`, `netstat`, `iostat` | built-in | `apt install net-tools sysstat` |
| ipx       | `ifconfig`, `route`/`ip`, `scutil` (mac) | built-in | `apt install net-tools iproute2` |
| pathx     | (none)                       | -     | -          |
| loadx     | `top`, `vm_stat`, `pmset`, `iostat`, `netstat`, `ioreg` (mac) | built-in | mac only |
| aix       | (none; reads `~/.claude/projects/`) | -     | -          |

### One-Shot Prerequisites (Reference)

**macOS** (system commands all built-in, only need Python):

```bash
# if brew is already installed
brew install python@3.12
```

**Ubuntu / Debian**:

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv \
    openssh-client openssl \
    iproute2 net-tools dnsutils sysstat \
    lsof traceroute iputils-ping
```

**Fedora / CentOS / RHEL**:

```bash
sudo dnf install -y \
    python3 \
    openssh-clients openssl \
    net-tools bind-utils sysstat \
    lsof traceroute iputils
```

## Install

```bash
git clone https://github.com/qzhello/tools.git
cd tools
./install.sh                    # install all tools
./install.sh ssh-alias jsonx    # install specific tools
./install.sh --lang en jsonx    # specify output language (default cn)
```

It automatically:

1. Symlinks each tool's command to `~/.local/bin/<tool>`
2. Adds `~/.local/bin` to your `PATH` (writes to `~/.zshrc` or `~/.bashrc`)
3. For tools with `source.sh` (e.g. `ssh-alias`), appends a source line to your shell rc

After installation, run `source ~/.zshrc` (or reopen the terminal) to take effect.

## Common Commands

```bash
./install.sh list                       # list all tools and install status
./install.sh --help                     # full help
./install.sh <tool> [<tool> ...]        # install one or more tools
./install.sh --uninstall                # uninstall all
./install.sh --uninstall <tool>         # uninstall specific tool
```

Example output of `./install.sh list`:

```
Available tools (12 total, 9 installed)

✓ base64x    base64 auto-detect, supports url-safe / file / clipboard I/O
✓ certx      HTTPS cert check, days-to-expiry + SAN + chain + TLS version
- dnsx       Multi-resolver DNS comparison with diff highlight (CDN/poisoning/propagation)
✓ datex      Timestamp ↔ date bidirectional, auto-detect 10/13/16/19-digit
...

✓ installed   - not installed
```

## Language Support

`install.sh` supports `--lang cn|en`, default `cn`:

- Chinese: full translation
- English: framework only (`MSG_en_*` variables); empty translations fall back to Chinese
- Other languages: error exit

To complete English translations, edit the `MSG_en_*` variables at the top of `install.sh`.

## Tool List

| Tool | Description |
|------|-------------|
| [ssh-alias](tools/ssh-alias/) | SSH quick login manager: key-based / password / password+TOTP 2FA auto-login (credentials encrypted in macOS Keychain), ControlMaster connection reuse |
| [cmd-alias](tools/cmd-alias/) | Shell command shortcuts (entry: `a`): register with `a add cc "<long command>"`, run with `a cc`; in zsh, `a <prefix>` + Tab expands/cycles matching history commands inline |
| [jsonx](tools/jsonx/)         | JSON pretty print, output to both stdout and clipboard, supports args / pipe / clipboard / file / directory |
| [datex](tools/datex/)         | Timestamp ↔ date bidirectional conversion, auto-detect 10/13/16/19-digit timestamps, multi-format output |
| [pingx](tools/pingx/)         | Real-time visual ping, sparkline + packet loss + min/avg/p95/max stats |
| [tracex](tools/tracex/)       | Visual route tracing (mtr-style), per-hop loss rate + latency sparkline |
| [dnsx](tools/dnsx/)           | Parallel multi-DNS-resolver comparison, diff highlighting, troubleshoot CDN/poisoning/propagation |
| [portx](tools/portx/)         | List local listening ports + processes, identify common services, supports `-k` to kill |
| [sizex](tools/sizex/)         | Directory size visualization, bar chart, sorted by size, find disk hogs |
| [procx](tools/procx/)         | Process viewer, sort by CPU/memory, color-highlighted, supports process tree and `-k` to kill |
| [certx](tools/certx/)         | HTTPS certificate check, days-to-expiry highlighted, SAN/chain/TLS version at a glance |
| [base64x](tools/base64x/)     | base64 bidirectional auto-detect, supports url-safe, file, clipboard I/O |
| [topx](tools/topx/)           | Clean system monitoring TUI, 4 quadrants (CPU/MEM/NET/DISK) + process list, single-key interaction |
| [ipx](tools/ipx/)             | Multi-source public IP + ISP/geo comparison, local interfaces v4/v6, default gateway, DNS overview |
| [pathx](tools/pathx/)         | $PATH visual diagnostics: status/binary count/source per entry, duplicate + missing + shadow detection, name lookup |
| [loadx](tools/loadx/)         | One-glance machine load: CPU/memory/network/disk/battery + top consumers + suggestions |
| [aix](tools/aix/)             | Claude Code + Codex token usage stats, TUI, aggregated by day/model/project/session/source |

## Adding a New Tool

1. Create a directory under `tools/`, e.g. `tools/my-tool/`
2. Create the main script `tools/my-tool/my-tool.sh` (chmod +x); put a one-line description on line 2: `# my-tool - description...`
3. If you need shell auto-loading, create `tools/my-tool/source.sh`
4. Run `./install.sh my-tool` to install

Directory structure:

```
tools/
├── install.sh              # unified install script
├── README.md
├── LICENSE
└── tools/
    ├── ssh-alias/
    │   ├── ssh-alias.sh    # main command
    │   ├── source.sh       # shell load (optional)
    │   └── README.md       # tool docs
    └── my-tool/
        ├── my-tool.sh
        └── README.md
```

## License

MIT
