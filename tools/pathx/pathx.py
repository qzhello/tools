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


# ---------- 渲染 ----------

def render_list(entries: List[Entry], filter_mode: Optional[str]) -> int:
    total = len(entries)
    n_dup = sum(1 for e in entries if e.duplicate_of)
    n_missing = sum(1 for e in entries if not e.exists or not e.is_dir)
    n_empty = sum(1 for e in entries if e.expanded.startswith("("))

    print(f"{BOLD}pathx{RESET}  $PATH 共 {total} 项"
          f"（{YELLOW if n_dup else DIM}{n_dup} 重复{RESET}，"
          f"{RED if n_missing else DIM}{n_missing} 不存在{RESET}"
          f"{f', {RED}{n_empty} 空条目（=cwd，危险）{RESET}' if n_empty else ''}）")
    print()

    # 按 filter 选条目
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

    # 计算列宽
    path_w = min(60, max(len(e.expanded) for e in selected))
    print(f"{DIM}  #   状态   {'目录':<{path_w - 2}}  {'binary':>7}  来源{RESET}")
    print(f"{DIM}{'─' * (4 + 8 + path_w + 11 + 30)}{RESET}")

    for e in selected:
        if not e.exists:
            status = f"{RED}✗ 缺{RESET}"
        elif not e.is_dir:
            status = f"{RED}✗ 非目录{RESET}"
        elif e.duplicate_of:
            status = f"{YELLOW}⚠ 重{RESET}"
        elif not e.readable:
            status = f"{YELLOW}⚠ 不可读{RESET}"
        elif e.expanded.startswith("("):
            status = f"{RED}⚠ 危{RESET}"
        else:
            status = f"{GREEN}✓{RESET}   "

        path_disp = e.expanded if e.expanded else e.raw or "(empty)"
        if len(path_disp) > path_w:
            path_disp = "…" + path_disp[-(path_w - 1):]

        bin_part = ""
        if e.duplicate_of:
            bin_part = f"{DIM}=#{e.duplicate_of}{RESET}"
        elif e.exists and e.is_dir:
            bin_part = f"{e.bin_count}"
        else:
            bin_part = f"{DIM}-{RESET}"

        src_part = ""
        if e.sources:
            shown = e.sources[0]
            # 缩短 home
            home = str(Path.home())
            shown = shown.replace(home, "~")
            if len(e.sources) > 1:
                shown += f" {DIM}(+{len(e.sources) - 1}){RESET}"
            src_part = f"{DIM}{shown}{RESET}"

        print(f"  {e.index:>2}  {status}   "
              f"{path_disp:<{path_w}}  "
              f"{bin_part:>7}  "
              f"{src_part}")

    return 0


def render_shadows(shadows: Dict[str, List[Tuple[int, str]]]) -> None:
    if not shadows:
        return
    print()
    print(f"{BOLD}遮蔽：{RESET}{len(shadows)} 个同名 binary 出现在多个目录")
    name_w = min(20, max(len(n) for n in shadows))
    # 按出现次数倒序
    for name in sorted(shadows, key=lambda k: (-len(shadows[k]), k)):
        paths = shadows[name]
        winner_idx, winner_path = paths[0]
        rest = paths[1:]
        print(f"  {CYAN}{name:<{name_w}}{RESET}  "
              f"{GREEN}#{winner_idx} {winner_path}{RESET}")
        for idx, p in rest:
            print(f"  {' ' * name_w}  {DIM}#{idx} {p}{RESET}")


def render_find(name: str, matches: List[Tuple[int, str, str]]) -> int:
    if not matches:
        print(f"{RED}✗ 在 PATH 中找不到 {name}{RESET}")
        return 1
    print(f"{BOLD}{name}{RESET}：找到 {len(matches)} 处")
    for i, (idx, full, real) in enumerate(matches):
        marker = f"{GREEN}✓ 生效{RESET}" if i == 0 else f"{DIM}· 被遮{RESET}"
        link = ""
        if real != full:
            home = str(Path.home())
            real_disp = real.replace(home, "~") if real.startswith(home) else real
            link = f"  {DIM}→ {real_disp}{RESET}"
        full_disp = full
        print(f"  {marker}  {YELLOW}#{idx}{RESET}  {full_disp}{link}")
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
    args = parser.parse_args()

    entries = parse_path()

    # 单 binary 查找
    if args.name:
        return render_find(args.name, find_binary(args.name, entries))

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

    # 末尾自动追加 shadows（不加 filter 时）
    if filter_mode is None:
        shadows = find_shadows(entries)
        render_shadows(shadows)

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
