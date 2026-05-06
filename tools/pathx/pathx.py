#!/usr/bin/env python3
"""pathx - $PATH 可视化与诊断。

用法：
  pathx                  列出 $PATH 每项 + 状态 + binary 数 + 来源猜测
  pathx <name>           找该 binary：按 PATH 顺序列出所有匹配，标出当前生效项
  pathx --dup            只显示重复条目
  pathx --missing        只显示不存在的目录
  pathx --shadows        只显示「同名 binary 在多个目录」
  pathx --check          有问题（重复/缺失/遮蔽）退出码非 0，给 CI 用
  pathx --raw            纯文本，每行一个 PATH 条目（去重去缺失，给脚本用）
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("PATHX_FORCE_COLOR") or sys.stdout.isatty())
)


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


DIM    = _c("\x1b[2m")
BOLD   = _c("\x1b[1m")
CYAN   = _c("\x1b[36m")
GREEN  = _c("\x1b[32m")
YELLOW = _c("\x1b[33m")
RED    = _c("\x1b[31m")
MAG    = _c("\x1b[35m")
BLUE   = _c("\x1b[34m")
GRAY   = _c("\x1b[90m")
RESET  = _c("\x1b[0m")


# ---------- PATH 解析 ----------

@dataclass
class Entry:
    index: int          # 1-based
    raw: str            # 原始字符串
    expanded: str       # 展开 ~ 后的绝对路径
    exists: bool = False
    is_dir: bool = False
    readable: bool = False
    bin_count: int = 0
    binaries: List[str] = field(default_factory=list)  # 不深扫，按需填
    duplicate_of: Optional[int] = None  # 指向首次出现的 index
    sources: List[str] = field(default_factory=list)   # 猜出来的来源 rc 文件


def parse_path() -> List[Entry]:
    raw_path = os.environ.get("PATH", "")
    items = raw_path.split(":")
    entries: List[Entry] = []
    seen: Dict[str, int] = {}  # expanded → first index
    for i, raw in enumerate(items, start=1):
        expanded = os.path.expanduser(raw) if raw else ""
        # 规范化但保留原样（去掉尾斜杠）
        norm = expanded.rstrip("/") if expanded != "/" else "/"
        e = Entry(index=i, raw=raw, expanded=norm or "")
        if not raw:
            # 空条目（PATH 里的 :: 表示当前目录，安全隐患）
            e.exists = True
            e.is_dir = True
            e.expanded = "(空 = 当前目录)"
        else:
            try:
                st = os.stat(norm)
                e.exists = True
                e.is_dir = stat.S_ISDIR(st.st_mode)
                e.readable = os.access(norm, os.R_OK | os.X_OK)
            except OSError:
                pass
        if e.exists and e.is_dir and norm:
            if norm in seen:
                e.duplicate_of = seen[norm]
            else:
                seen[norm] = i
        entries.append(e)
    return entries


def count_binaries(entry: Entry) -> int:
    """快扫该目录下可执行文件数（不递归，跳隐藏文件）。"""
    if not (entry.exists and entry.is_dir and entry.readable):
        return 0
    if entry.expanded.startswith("("):
        return 0
    n = 0
    try:
        with os.scandir(entry.expanded) as it:
            for de in it:
                if de.name.startswith("."):
                    continue
                try:
                    if de.is_file(follow_symlinks=True) or de.is_symlink():
                        if os.access(de.path, os.X_OK):
                            n += 1
                except OSError:
                    pass
    except OSError:
        pass
    return n


# ---------- 来源猜测 ----------

# 候选 rc 文件，按典型加载顺序
RC_CANDIDATES = [
    "/etc/zshenv", "/etc/zprofile", "/etc/zshrc",
    "/etc/profile", "/etc/bashrc", "/etc/paths",
    "~/.zshenv", "~/.zprofile", "~/.zshrc", "~/.zlogin",
    "~/.bash_profile", "~/.bashrc", "~/.profile",
    "~/.config/fish/config.fish",
]


def _read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def guess_sources(entries: List[Entry]) -> None:
    """对每条 PATH 项，扫常见 rc 文件看哪些行可能添加了它。"""
    home = str(Path.home())

    # 收集 (rc_file, idx, line_text)；只对包含 PATH 或常见添加模式的行感兴趣
    rc_lines: List[Tuple[str, int, str]] = []
    for cand in RC_CANDIDATES:
        path = os.path.expanduser(cand)
        for i, line in enumerate(_read_lines(path), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 关心的行：含 PATH= 或 export PATH 或 path+= 或 brew shellenv 或 fnm/nvm/pyenv init
            if re.search(r"\b(PATH=|export\s+PATH|path\+=|fpath\+=)", stripped) \
               or re.search(r"\b(shellenv|nvm|pyenv|rbenv|nodenv|fnm|sdkman|asdf|cargo/env)\b", stripped):
                rc_lines.append((cand, i, stripped))

    # /etc/paths 和 /etc/paths.d/*：每行一个目录
    paths_d_files = ["/etc/paths"]
    try:
        for f in sorted(os.listdir("/etc/paths.d")):
            paths_d_files.append(f"/etc/paths.d/{f}")
    except OSError:
        pass
    paths_d_map: Dict[str, str] = {}
    for pf in paths_d_files:
        for line in _read_lines(pf):
            d = line.strip()
            if d:
                paths_d_map.setdefault(d, pf)

    for e in entries:
        if not e.expanded or e.expanded.startswith("("):
            continue
        # 1) /etc/paths(.d) 直接对应
        if e.expanded in paths_d_map:
            e.sources.append(paths_d_map[e.expanded])
            continue
        # 2) rc 文件中的字面包含
        # 用 raw 和 expanded 都试一次（raw 可能含 $HOME 或 ~）
        candidates: Set[str] = set()
        for rc, line_no, text in rc_lines:
            if e.expanded and e.expanded in text:
                candidates.add(f"{rc}:{line_no}")
                continue
            if e.raw and e.raw in text and e.raw != e.expanded:
                candidates.add(f"{rc}:{line_no}")
                continue
            # brew shellenv 模式
            if "shellenv" in text and e.expanded.startswith(("/opt/homebrew", "/usr/local/Homebrew", "/usr/local/Cellar")):
                candidates.add(f"{rc}:{line_no} (brew shellenv)")
        for c in sorted(candidates):
            e.sources.append(c)


# ---------- 遮蔽检测 ----------

def find_shadows(entries: List[Entry]) -> Dict[str, List[Tuple[int, str]]]:
    """返回 {binary 名: [(entry_index, full_path), ...]}，只保留出现 ≥2 次的。"""
    seen: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for e in entries:
        if not (e.exists and e.is_dir and e.readable) or e.duplicate_of:
            continue
        try:
            with os.scandir(e.expanded) as it:
                for de in it:
                    if de.name.startswith("."):
                        continue
                    if not (de.is_file(follow_symlinks=True) or de.is_symlink()):
                        continue
                    if not os.access(de.path, os.X_OK):
                        continue
                    seen[de.name].append((e.index, de.path))
        except OSError:
            continue
    return {k: v for k, v in seen.items() if len(v) >= 2}


# ---------- 单 binary 查找 ----------

def find_binary(name: str, entries: List[Entry]) -> List[Tuple[int, str, str]]:
    """返回 [(entry_index, full_path, 解析后的真实路径)]，按 PATH 顺序。"""
    matches: List[Tuple[int, str, str]] = []
    for e in entries:
        if not (e.exists and e.is_dir):
            continue
        if e.expanded.startswith("("):
            continue
        full = os.path.join(e.expanded, name)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            try:
                real = os.path.realpath(full)
            except OSError:
                real = full
            matches.append((e.index, full, real))
    return matches


# 常见「装了但可能没进 PATH」的目录模式
# 用 glob 风格；占位符 ${HOME} 会被替换
_OFFPATH_PATTERNS = [
    # Go：手动 SDK / go install 产物
    "${HOME}/sdk/*/bin",
    "${HOME}/go/bin",
    "/usr/local/go/bin",
    # Python
    "${HOME}/.pyenv/versions/*/bin",
    "${HOME}/.pyenv/shims",
    "${HOME}/Library/Python/*/bin",
    "/Library/Frameworks/Python.framework/Versions/*/bin",
    # Node
    "${HOME}/.nvm/versions/node/*/bin",
    "${HOME}/.fnm/node-versions/*/installation/bin",
    "${HOME}/.volta/bin",
    "${HOME}/.npm-global/bin",
    # Ruby
    "${HOME}/.rbenv/versions/*/bin",
    "${HOME}/.rbenv/shims",
    "${HOME}/.rvm/rubies/*/bin",
    # JVM
    "${HOME}/.sdkman/candidates/*/current/bin",
    "${HOME}/.jenv/versions/*/bin",
    "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin",
    # Rust / Cargo
    "${HOME}/.cargo/bin",
    "${HOME}/.rustup/toolchains/*/bin",
    # asdf
    "${HOME}/.asdf/installs/*/*/bin",
    "${HOME}/.asdf/shims",
    # Homebrew Cellar 的所有版本
    "/opt/homebrew/Cellar/*/*/bin",
    "/opt/homebrew/opt/*/bin",
    "/usr/local/Cellar/*/*/bin",
    "/usr/local/opt/*/bin",
    # MacPorts
    "/opt/local/lib/*/bin",
    # 用户常见
    "${HOME}/.local/bin",
    "${HOME}/bin",
    # Conda / Mamba
    "${HOME}/miniconda3/envs/*/bin",
    "${HOME}/miniforge3/envs/*/bin",
    "${HOME}/anaconda3/envs/*/bin",
]


def find_binary_off_path(
    name: str,
    in_path_set: Set[str],
) -> List[str]:
    """扫常见 dev-tool 安装位置，返回不在 PATH 里的同名可执行 full_path 列表。"""
    import glob
    home = str(Path.home())
    out: List[str] = []
    seen: Set[str] = set()
    for pat in _OFFPATH_PATTERNS:
        expanded = pat.replace("${HOME}", home)
        for d in glob.glob(expanded):
            if d in in_path_set:
                continue
            full = os.path.join(d, name)
            if full in seen:
                continue
            try:
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    out.append(full)
                    seen.add(full)
            except OSError:
                pass
    # 按真实路径分组，去掉 symlink 指向同一物的重复
    by_real: Dict[str, str] = {}
    for full in out:
        try:
            real = os.path.realpath(full)
        except OSError:
            real = full
        by_real.setdefault(real, full)
    # 保留原顺序
    keep: List[str] = []
    seen_real: Set[str] = set()
    for full in out:
        try:
            real = os.path.realpath(full)
        except OSError:
            real = full
        if real in seen_real:
            continue
        seen_real.add(real)
        keep.append(full)
    return keep


# ---------- 渲染 ----------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _disp_w(s: str) -> int:
    bare = _ANSI_RE.sub("", s)
    w = 0
    for ch in bare:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def _ljust_w(s: str, width: int) -> str:
    pad = width - _disp_w(s)
    return s + (" " * pad if pad > 0 else "")


def _rjust_w(s: str, width: int) -> str:
    pad = width - _disp_w(s)
    return (" " * pad if pad > 0 else "") + s


def _short_home(s: str) -> str:
    home = str(Path.home())
    return s.replace(home, "~") if s.startswith(home) else s


def _status_for(e: Entry) -> Tuple[str, str]:
    """返回 (符号, 颜色)"""
    if e.expanded.startswith("("):
        return ("!", RED)
    if not e.exists or not e.is_dir:
        return ("✗", RED)
    if e.duplicate_of:
        return ("⚠", YELLOW)
    if not e.readable:
        return ("⚠", YELLOW)
    return ("✓", GREEN)


def render_list(entries: List[Entry], filter_mode: Optional[str]) -> int:
    total = len(entries)
    n_dup = sum(1 for e in entries if e.duplicate_of)
    n_missing = sum(1 for e in entries if not e.exists or not e.is_dir)
    n_empty = sum(1 for e in entries if e.expanded.startswith("("))

    parts = [f"{BOLD}{total}{RESET} 项"]
    parts.append(f"{(YELLOW if n_dup else DIM)}{n_dup} 重复{RESET}")
    parts.append(f"{(RED if n_missing else DIM)}{n_missing} 不存在{RESET}")
    if n_empty:
        parts.append(f"{RED}{n_empty} 空条目（=cwd，危险）{RESET}")
    print(f"{CYAN}{BOLD}$PATH{RESET}  " + f"  {DIM}·{RESET}  ".join(parts))
    print()

    selected = []
    for e in entries:
        if filter_mode == "dup" and not e.duplicate_of:
            continue
        if filter_mode == "missing" and (e.exists and e.is_dir):
            continue
        selected.append(e)

    if not selected:
        print(f"{DIM}(无匹配条目){RESET}")
        return 0

    # 列宽（按显示宽度算）
    home = str(Path.home())
    paths = [_short_home(e.expanded if e.expanded else e.raw or "(empty)") for e in selected]
    path_w = min(60, max(_disp_w(p) for p in paths))
    idx_w = max(3, len(f"#{max(e.index for e in selected)}"))
    n_w = max(3, len(str(max((e.bin_count for e in selected if e.bin_count), default=0))))

    # 表头
    header = (
        f"  {DIM}{_ljust_w('', 1)} "
        f"{_ljust_w('#', idx_w)}  "
        f"{_ljust_w('目录', path_w)}  "
        f"{_rjust_w('命令', n_w)}  "
        f"来源{RESET}"
    )
    print(header)
    print(f"{DIM}{'─' * (2 + 1 + 1 + idx_w + 2 + path_w + 2 + n_w + 2 + 24)}{RESET}")

    for e, path_disp in zip(selected, paths):
        if _disp_w(path_disp) > path_w:
            # 截断保留尾部
            while _disp_w(path_disp) > path_w - 1:
                path_disp = path_disp[1:]
            path_disp = "…" + path_disp

        sym, color = _status_for(e)
        status = f"{color}{sym}{RESET}"

        idx_str = f"{color}#{e.index}{RESET}"

        if e.duplicate_of:
            n_str = f"{YELLOW}=#{e.duplicate_of}{RESET}"
            path_color = DIM
        elif not e.exists or not e.is_dir:
            n_str = f"{DIM}-{RESET}"
            path_color = DIM + RED
        else:
            n_str = f"{e.bin_count}"
            path_color = ""

        src_str = ""
        if e.sources:
            first = _short_home(e.sources[0])
            src_str = f"{DIM}{first}{RESET}"
            if len(e.sources) > 1:
                src_str += f"{DIM} +{len(e.sources) - 1}{RESET}"

        print(
            f"  {status} "
            f"{_ljust_w(idx_str, idx_w)}  "
            f"{_ljust_w(path_color + path_disp + RESET, path_w)}  "
            f"{_rjust_w(n_str, n_w)}  "
            f"{src_str}"
        )

    return 0


def render_shadows(shadows: Dict[str, List[Tuple[int, str]]], limit: int = 0) -> None:
    if not shadows:
        return
    print()
    total = len(shadows)
    items = sorted(shadows.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    shown = items if limit <= 0 else items[:limit]

    title = f"{BOLD}遮蔽{RESET}  {total} 个命令同名出现在多个目录"
    if limit > 0 and total > limit:
        title += f"  {DIM}（仅显示前 {limit}，--shadows 看全部）{RESET}"
    print(title)
    print()

    name_w = min(20, max(_disp_w(n) for n, _ in shown))
    for name, paths in shown:
        winner_idx, winner_full = paths[0]
        winner_dir = os.path.dirname(winner_full)
        winner_dir = _short_home(winner_dir)
        shadow_idxs = ",".join(f"#{p[0]}" for p in paths[1:])
        print(
            f"  {CYAN}{_ljust_w(name, name_w)}{RESET}  "
            f"{GREEN}#{winner_idx}{RESET} {winner_dir}  "
            f"{DIM}← 被 {shadow_idxs} 遮{RESET}"
        )


def render_find(
    name: str,
    matches: List[Tuple[int, str, str]],
    off_path: List[str],
) -> int:
    if not matches and not off_path:
        print(f"{RED}✗{RESET} 在 PATH 和常见安装位置都找不到 {BOLD}{name}{RESET}")
        return 1

    head = f"{CYAN}{BOLD}{name}{RESET}  "
    parts = []
    if matches:
        parts.append(f"{DIM}PATH 中 {len(matches)} 处{RESET}")
    if off_path:
        parts.append(f"{YELLOW}另有 {len(off_path)} 处装着但未启用{RESET}")
    print(head + "  ·  ".join(parts))
    print()

    if matches:
        for i, (idx, full, real) in enumerate(matches):
            if i == 0:
                sym = f"{GREEN}✓{RESET}"
                tag = f"{GREEN}生效{RESET}"
                path_color = ""
            else:
                sym = f"{DIM}·{RESET}"
                tag = f"{DIM}被遮{RESET}"
                path_color = DIM
            idx_str = f"#{idx}"
            print(f"  {sym} {tag}  {YELLOW}{idx_str:<4}{RESET}  {path_color}{_short_home(full)}{RESET}")
            if real != full:
                print(f"        {DIM}→ {_short_home(real)}{RESET}")

    if off_path:
        if matches:
            print()
        print(f"  {YELLOW}未在 PATH 但已安装{RESET}  {DIM}（加进 PATH 即可启用）{RESET}")
        for full in off_path:
            try:
                real = os.path.realpath(full)
            except OSError:
                real = full
            full_disp = _short_home(full)
            print(f"  {DIM}○{RESET}        {YELLOW}--{RESET}    {full_disp}")
            if real != full:
                print(f"        {DIM}→ {_short_home(real)}{RESET}")
    return 0


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pathx",
        description="$PATH 可视化与诊断",
    )
    parser.add_argument("name", nargs="?", help="按名查找该 binary 在 PATH 里的所有匹配")
    parser.add_argument("--dup", action="store_true", help="只显示重复条目")
    parser.add_argument("--missing", action="store_true", help="只显示不存在/非目录的条目")
    parser.add_argument("--shadows", action="store_true", help="只显示被遮蔽的同名 binary")
    parser.add_argument("--check", action="store_true", help="有问题（重复/缺失）退出码非 0")
    parser.add_argument("--raw", action="store_true", help="纯文本一行一个 PATH 条目（去重去缺失），给脚本用")
    parser.add_argument("--no-source", action="store_true", help="跳过来源猜测（更快）")
    parser.add_argument("--no-count", action="store_true", help="跳过 binary 计数（更快）")
    parser.add_argument("--no-offpath", action="store_true", help="按名查找时不扫常见安装位置")
    args = parser.parse_args()

    entries = parse_path()

    # 单 binary 查找
    if args.name:
        in_path_set = {e.expanded for e in entries if e.exists and e.is_dir}
        matches = find_binary(args.name, entries)
        off_path = [] if args.no_offpath else find_binary_off_path(args.name, in_path_set)
        return render_find(args.name, matches, off_path)

    # raw 输出：去重 + 跳过缺失，给 shell 用
    if args.raw:
        seen: Set[str] = set()
        for e in entries:
            if not (e.exists and e.is_dir) or e.duplicate_of or e.expanded.startswith("("):
                continue
            if e.expanded in seen:
                continue
            seen.add(e.expanded)
            print(e.expanded)
        return 0

    # 计数 + 来源（带选项跳过）
    if not args.no_count:
        for e in entries:
            if e.duplicate_of:
                continue
            e.bin_count = count_binaries(e)
    if not args.no_source:
        guess_sources(entries)

    # filter mode
    filter_mode = None
    if args.dup:
        filter_mode = "dup"
    elif args.missing:
        filter_mode = "missing"

    if args.shadows:
        # 不打 list，只打 shadows
        shadows = find_shadows(entries)
        if not shadows:
            print(f"{GREEN}✓ 未发现被遮蔽的命令{RESET}")
            return 0
        render_shadows(shadows)
        return 0

    render_list(entries, filter_mode)

    # 末尾自动追加 shadows（不加 filter 时；只显示前 10）
    if filter_mode is None:
        shadows = find_shadows(entries)
        render_shadows(shadows, limit=10)

    if args.check:
        n_dup = sum(1 for e in entries if e.duplicate_of)
        n_missing = sum(1 for e in entries if not e.exists or not e.is_dir)
        if n_dup or n_missing:
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
