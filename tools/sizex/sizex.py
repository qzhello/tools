#!/usr/bin/env python3
"""sizex - 目录大小可视化。

显示指定路径下前 N 个最大的子项（默认目录），带条形图。
也支持 -f 递归找最大文件。
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import shutil
import sys
import time
from typing import List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("SIZEX_FORCE_COLOR") or sys.stdout.isatty())
)


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


DIM    = _c("\x1b[2m")
BOLD   = _c("\x1b[1m")
CYAN   = _c("\x1b[36m")
GREEN  = _c("\x1b[32m")
YELLOW = _c("\x1b[33m")
RED    = _c("\x1b[31m")
BLUE   = _c("\x1b[34m")
GRAY   = _c("\x1b[90m")
RESET  = _c("\x1b[0m")

UNITS = ("B", "K", "M", "G", "T", "P")


def humanize(n: int) -> str:
    f = float(n)
    for u in UNITS:
        if f < 1024 or u == UNITS[-1]:
            if u == "B":
                return f"{int(f)} {u}"
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} P"


def color_for_size(n: int) -> str:
    # 大小颜色梯度
    if n >= 1024 ** 3:        # >= 1 GB
        return RED
    if n >= 100 * 1024 ** 2:  # >= 100 MB
        return YELLOW
    if n >= 1024 ** 2:        # >= 1 MB
        return GREEN
    return DIM


def dir_size(path: str, follow: bool = False) -> int:
    """递归计算目录占用字节数。失败的项跳过。"""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if not follow and entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=follow)
                        if entry.is_file(follow_symlinks=follow):
                            total += st.st_size
                        elif entry.is_dir(follow_symlinks=follow):
                            stack.append(entry.path)
                    except (PermissionError, OSError, FileNotFoundError):
                        continue
        except (PermissionError, OSError, FileNotFoundError):
            continue
    return total


def collect_top_level(path: str, include_hidden: bool, follow: bool) -> List[Tuple[str, int, str]]:
    """返回 path 下一级条目的 (name, bytes, kind) 列表。"""
    out: List[Tuple[str, int, str]] = []
    try:
        entries = list(os.scandir(path))
    except (PermissionError, OSError, FileNotFoundError) as e:
        sys.exit(f"✗ 读取失败: {e}")
    for entry in entries:
        if not include_hidden and entry.name.startswith("."):
            continue
        try:
            if not follow and entry.is_symlink():
                size = 0
                kind = "link"
            elif entry.is_dir(follow_symlinks=follow):
                size = dir_size(entry.path, follow=follow)
                kind = "dir"
            else:
                size = entry.stat(follow_symlinks=follow).st_size
                kind = "file"
        except (PermissionError, OSError, FileNotFoundError):
            continue
        out.append((entry.name, size, kind))
    return out


def collect_files(path: str, include_hidden: bool, follow: bool) -> List[Tuple[str, int, str]]:
    """递归收集所有文件。返回 (相对路径, bytes, 'file')。"""
    out: List[Tuple[str, int, str]] = []
    base_len = len(os.path.abspath(path).rstrip(os.sep)) + 1
    stack = [os.path.abspath(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    try:
                        if not follow and entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=follow):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=follow):
                            size = entry.stat(follow_symlinks=follow).st_size
                            rel = entry.path[base_len:] if entry.path.startswith(cur) or len(entry.path) > base_len else entry.path
                            # 用绝对路径减去 base 得到相对
                            ap = os.path.abspath(entry.path)
                            rel = ap[base_len:] if len(ap) > base_len else ap
                            out.append((rel, size, "file"))
                    except (PermissionError, OSError, FileNotFoundError):
                        continue
        except (PermissionError, OSError, FileNotFoundError):
            continue
    return out


def kind_marker(kind: str) -> str:
    if kind == "dir":
        return f"{BLUE}/"
    if kind == "link":
        return f"{CYAN}@"
    return ""


def render_bar(ratio: float, width: int) -> str:
    if width <= 0:
        return ""
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    if _USE_COLOR:
        return "█" * filled + f"{DIM}{'░' * empty}{RESET}"
    return "█" * filled + "░" * empty


def disp_width(s: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in s)


def render(entries: List[Tuple[str, int, str]], top: int, show_bar: bool, total: Optional[int], path: str) -> None:
    if not entries:
        print(f"{DIM}（空目录或无可读项）{RESET}")
        return
    entries = sorted(entries, key=lambda x: x[1], reverse=True)
    shown = entries[:top]
    rest = entries[top:]
    rest_size = sum(e[1] for e in rest)

    grand = total if total is not None else sum(e[1] for e in entries)

    # 头
    print(f"{BOLD}{path}{RESET}  {DIM}（{len(entries)} 项，总计 {humanize(grand)}）{RESET}")
    print()

    if not shown:
        return

    # 列宽
    max_size = max(e[1] for e in shown)
    size_w = max(len(humanize(e[1])) for e in shown)
    name_w = max(disp_width(e[0] + ("/" if e[2] == "dir" else "")) for e in shown)

    # bar 宽度：终端宽 - size_w - name_w - 一些 margin
    term_w = shutil.get_terminal_size((100, 24)).columns
    fixed = size_w + name_w + 8
    bar_w = max(8, min(40, term_w - fixed))

    for name, size, kind in shown:
        ratio = (size / max_size) if max_size else 0
        bar = render_bar(ratio, bar_w) if show_bar else ""
        size_s = humanize(size).rjust(size_w)
        size_col = f"{color_for_size(size)}{size_s}{RESET}"
        marker = kind_marker(kind)
        name_disp = f"{marker}{name}{RESET}" if marker else name
        if show_bar:
            print(f"  {bar}  {size_col}  {name_disp}")
        else:
            print(f"  {size_col}  {name_disp}")

    if rest:
        print(f"  {DIM}... 还有 {len(rest)} 项，共 {humanize(rest_size)}{RESET}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sizex",
        description="目录大小可视化（按大小排序，条形图）",
    )
    p.add_argument("path", nargs="?", default=".", help="目标路径（默认当前目录）")
    p.add_argument("-n", "--top", type=int, default=20, help="显示前 N 项（默认 20）")
    p.add_argument("-a", "--all", action="store_true", help="包含隐藏文件 / 目录")
    p.add_argument("-f", "--files", action="store_true", help="递归找最大文件（而不是只看一级）")
    p.add_argument("-L", "--follow", action="store_true", help="跟随符号链接（默认不跟随）")
    p.add_argument("--no-bar", action="store_true", help="不画条形图")
    p.add_argument("-j", "--json", action="store_true", help="JSON 输出（脚本用）")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    path = os.path.abspath(args.path)
    if not os.path.exists(path):
        print(f"✗ 路径不存在: {args.path}", file=sys.stderr)
        return 1
    if not os.path.isdir(path):
        # 单文件直接报大小
        size = os.path.getsize(path)
        if args.json:
            print(jsonlib.dumps({"path": path, "size": size}, ensure_ascii=False))
        else:
            print(f"{humanize(size)}  {path}")
        return 0

    if args.top < 1:
        print("✗ -n 至少 1", file=sys.stderr)
        return 1

    t0 = time.monotonic()
    if args.files:
        entries = collect_files(path, include_hidden=args.all, follow=args.follow)
    else:
        entries = collect_top_level(path, include_hidden=args.all, follow=args.follow)
    elapsed = time.monotonic() - t0

    if args.json:
        out = [{"name": n, "size": s, "kind": k}
               for n, s, k in sorted(entries, key=lambda x: x[1], reverse=True)[:args.top]]
        print(jsonlib.dumps(out, ensure_ascii=False, indent=2))
        return 0

    render(entries, top=args.top, show_bar=not args.no_bar, total=None, path=path)
    if elapsed > 1.0:
        print(f"\n{DIM}扫描用时 {elapsed:.1f}s{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
