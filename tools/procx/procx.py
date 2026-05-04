#!/usr/bin/env python3
"""procx - 进程查看器。

包装 ps，按 CPU/内存排序，过滤，颜色高亮。
支持 -t 进程树视图、-k 杀进程（带二次确认）。
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("PROCX_FORCE_COLOR") or sys.stdout.isatty())
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
GRAY   = _c("\x1b[90m")
RESET  = _c("\x1b[0m")


def collect() -> List[Dict]:
    cmd = ["ps", "-eo", "pid,ppid,user,pcpu,pmem,rss,etime,command"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError:
        sys.exit("✗ 找不到 ps")
    out = proc.stdout.decode("utf-8", errors="replace")
    procs: List[Dict] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, ppid, user, pcpu, pmem, rss, etime, command = parts
        try:
            procs.append({
                "pid": int(pid),
                "ppid": int(ppid),
                "user": user,
                "pcpu": float(pcpu),
                "pmem": float(pmem),
                "rss_kb": int(rss),
                "etime": etime,
                "etime_sec": parse_etime(etime),
                "command": command,
            })
        except ValueError:
            continue
    return procs


def parse_etime(s: str) -> int:
    """ps ELAPSED 格式：[[DD-]HH:]MM:SS。返回秒。"""
    days = 0
    rest = s
    if "-" in s:
        a, rest = s.split("-", 1)
        try:
            days = int(a)
        except ValueError:
            pass
    parts = rest.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    h, m, sec = 0, 0, 0
    if len(nums) == 3:
        h, m, sec = nums
    elif len(nums) == 2:
        m, sec = nums
    elif len(nums) == 1:
        sec = nums[0]
    return days * 86400 + h * 3600 + m * 60 + sec


def fmt_etime(sec: int) -> str:
    if sec >= 86400:
        d = sec // 86400
        h = (sec % 86400) // 3600
        return f"{d}d{h}h"
    if sec >= 3600:
        h = sec // 3600
        m = (sec % 3600) // 60
        return f"{h}h{m}m"
    if sec >= 60:
        return f"{sec // 60}m{sec % 60}s"
    return f"{sec}s"


def fmt_mem(kb: int) -> str:
    f = kb * 1024.0
    for u in ("B", "K", "M", "G", "T"):
        if f < 1024 or u == "T":
            if u in ("B", "K"):
                return f"{int(f)}{u}"
            return f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}T"


def cpu_color(v: float) -> str:
    if v >= 80:  return RED
    if v >= 30:  return YELLOW
    if v >= 1:   return GREEN
    return DIM


def mem_pct_color(v: float) -> str:
    if v >= 50:  return RED
    if v >= 20:  return YELLOW
    if v >= 1:   return GREEN
    return DIM


def mem_size_color(kb: int) -> str:
    if kb >= 1024 ** 2:        return RED       # >= 1 GB
    if kb >= 256 * 1024:       return YELLOW    # >= 256 MB
    if kb >= 10 * 1024:        return GREEN     # >= 10 MB
    return DIM


def time_color(sec: int) -> str:
    if sec >= 86400 * 7:  return CYAN
    if sec >= 86400:      return MAG
    if sec >= 3600:       return RESET
    return DIM


def matches(p: Dict, q: Optional[str]) -> bool:
    if not q:
        return True
    if q.isdigit() and len(q) <= 7:
        # PID 完全匹配
        return p["pid"] == int(q)
    ql = q.lower()
    return ql in p["command"].lower() or ql in p["user"].lower()


def disp_width(s: str) -> int:
    w = 0
    for c in s:
        o = ord(c)
        if o < 32:
            continue
        w += 2 if o > 127 else 1
    return w


def truncate(s: str, w: int) -> str:
    if disp_width(s) <= w:
        return s
    out = []
    cur = 0
    for c in s:
        cw = 2 if ord(c) > 127 else 1
        if cur + cw > w - 1:
            break
        out.append(c)
        cur += cw
    return "".join(out) + "…"


def render_flat(procs: List[Dict], top: int) -> None:
    if not procs:
        print(f"{DIM}（没有匹配的进程）{RESET}")
        return

    shown = procs[:top]
    rest = procs[top:]

    cols = ["PID", "USER", "%CPU", "%MEM", "RSS", "TIME", "命令"]
    rows = []
    for p in shown:
        rows.append([
            str(p["pid"]),
            p["user"],
            f"{p['pcpu']:.1f}",
            f"{p['pmem']:.1f}",
            fmt_mem(p["rss_kb"]),
            fmt_etime(p["etime_sec"]),
            p["command"],
        ])

    # 列宽（命令列另外算）
    fixed_widths = [
        max(disp_width(cols[i]),
            max((disp_width(r[i]) for r in rows), default=0))
        for i in range(6)
    ]

    term_w = shutil.get_terminal_size((100, 24)).columns
    used = sum(fixed_widths) + 2 * 6 + 2  # 列间空白
    cmd_w = max(20, term_w - used)

    # 表头
    hdr = []
    for i, c in enumerate(cols[:6]):
        hdr.append(f"{CYAN}{c.rjust(fixed_widths[i]) if c.startswith('%') or c == 'RSS' or c == 'TIME' else c.ljust(fixed_widths[i])}{RESET}")
    hdr.append(f"{CYAN}{cols[6]}{RESET}")
    print("  ".join(hdr))
    print(DIM + "  ".join("─" * w for w in fixed_widths) + "  " + "─" * cmd_w + RESET)

    for p, r in zip(shown, rows):
        pid_col  = f"{DIM}{r[0].rjust(fixed_widths[0])}{RESET}"
        user_col = r[1].ljust(fixed_widths[1])
        cpu_col  = f"{cpu_color(p['pcpu'])}{r[2].rjust(fixed_widths[2])}{RESET}"
        mem_col  = f"{mem_pct_color(p['pmem'])}{r[3].rjust(fixed_widths[3])}{RESET}"
        rss_col  = f"{mem_size_color(p['rss_kb'])}{r[4].rjust(fixed_widths[4])}{RESET}"
        time_col = f"{time_color(p['etime_sec'])}{r[5].rjust(fixed_widths[5])}{RESET}"
        cmd_col  = truncate(r[6], cmd_w)
        print(f"{pid_col}  {user_col}  {cpu_col}  {mem_col}  {rss_col}  {time_col}  {cmd_col}")

    if rest:
        print(f"\n{DIM}... 还有 {len(rest)} 个进程未显示（用 -n 调大上限）{RESET}")


def render_tree(procs: List[Dict], top: int, sort_key: str) -> None:
    by_pid = {p["pid"]: p for p in procs}
    children: Dict[int, List[int]] = {}
    for p in procs:
        children.setdefault(p["ppid"], []).append(p["pid"])
    # 排序子节点（按 sort_key 降序）
    for pids in children.values():
        pids.sort(key=lambda pid: -by_pid[pid].get(sort_key, 0) if pid in by_pid else 0)

    roots = [p["pid"] for p in procs if p["ppid"] not in by_pid]
    roots.sort(key=lambda pid: -by_pid[pid][sort_key])

    term_w = shutil.get_terminal_size((100, 24)).columns
    counter = {"n": 0}

    def emit(pid: int, prefix: str, is_last: bool, is_root: bool) -> None:
        if counter["n"] >= top:
            return
        counter["n"] += 1
        p = by_pid[pid]
        connector = ("└─ " if is_last else "├─ ") if not is_root else ""
        head = f"{prefix}{connector}"
        meta = (
            f"{cpu_color(p['pcpu'])}{p['pcpu']:5.1f}%CPU{RESET} "
            f"{mem_size_color(p['rss_kb'])}{fmt_mem(p['rss_kb']):>7}{RESET} "
            f"{DIM}{p['pid']:>6}{RESET} "
        )
        avail = term_w - disp_width(head) - disp_width(meta) - 2
        cmd = truncate(p["command"], max(20, avail))
        print(f"{head}{meta}{cmd}")

        kids = children.get(pid, [])
        new_prefix = prefix + ("   " if is_last else "│  ") if not is_root else prefix
        for i, k in enumerate(kids):
            if counter["n"] >= top:
                break
            emit(k, new_prefix, i == len(kids) - 1, False)

    for i, root in enumerate(roots):
        if counter["n"] >= top:
            break
        emit(root, "", i == len(roots) - 1, True)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_kill(procs: List[Dict], assume_yes: bool) -> int:
    if not procs:
        print("没有匹配的进程")
        return 1
    print(f"将 {RED}杀掉{RESET} 以下 {len(procs)} 个进程：")
    for p in procs:
        cmd = truncate(p["command"], 80)
        print(f"  PID {DIM}{p['pid']:>6}{RESET}  {cpu_color(p['pcpu'])}{p['pcpu']:>5.1f}%CPU{RESET}  "
              f"{mem_size_color(p['rss_kb'])}{fmt_mem(p['rss_kb']):>7}{RESET}  "
              f"{DIM}({p['user']}){RESET}  {cmd}")
    if not assume_yes:
        try:
            ans = input(f"\n确认？{DIM}[y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 0
        if ans not in ("y", "yes"):
            print("已取消")
            return 0

    pids = [p["pid"] for p in procs]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  {YELLOW}SIGTERM{RESET} → {pid}")
        except ProcessLookupError:
            print(f"  {DIM}进程 {pid} 已退出{RESET}")
        except PermissionError:
            print(f"  {RED}无权限{RESET} → {pid}（可能需要 sudo）")

    time.sleep(2)
    still = [pid for pid in pids if pid_alive(pid)]
    if not still:
        print(f"\n{GREEN}全部已退出{RESET}")
        return 0
    print(f"\n{YELLOW}{len(still)} 个进程未响应{RESET}")
    if not assume_yes:
        try:
            ans = input(f"用 SIGKILL 强杀？{DIM}[y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 0
        if ans not in ("y", "yes"):
            return 0
    for pid in still:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  {RED}SIGKILL{RESET} → {pid}")
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  {RED}无权限{RESET} → {pid}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="procx",
        description="进程查看器（按 CPU/内存排序，可过滤，可杀）",
    )
    p.add_argument("filter", nargs="?", default=None,
                   help="按命令名 / 用户名（字符串）或 PID（纯数字）过滤")
    p.add_argument("-n", "--top", type=int, default=20, help="显示前 N 个（默认 20）")
    p.add_argument("-m", "--by-mem", action="store_true", help="按内存排序（默认按 CPU）")
    p.add_argument("-t", "--tree", action="store_true", help="按进程树展示")
    p.add_argument("-k", "--kill", action="store_true", help="杀掉匹配的进程")
    p.add_argument("-y", "--yes", action="store_true", help="--kill 时跳过所有确认")
    p.add_argument("-j", "--json", action="store_true", help="JSON 输出")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    procs = collect()
    procs = [p for p in procs if matches(p, args.filter)]

    sort_key = "rss_kb" if args.by_mem else "pcpu"
    procs.sort(key=lambda p: p[sort_key], reverse=True)

    if args.kill:
        if not args.filter:
            print("✗ --kill 需要指定过滤条件（PID 或进程名）", file=sys.stderr)
            return 1
        # 杀的时候不限 top；但限制下避免误杀全机
        if len(procs) > 50 and not args.yes:
            print(f"✗ 匹配到 {len(procs)} 个进程，太多了。请先精确过滤，或加 -y 强制",
                  file=sys.stderr)
            return 1
        return cmd_kill(procs, assume_yes=args.yes)

    if args.json:
        out = []
        for p in procs[:args.top]:
            out.append({k: p[k] for k in
                        ("pid", "ppid", "user", "pcpu", "pmem", "rss_kb",
                         "etime", "etime_sec", "command")})
        print(jsonlib.dumps(out, ensure_ascii=False, indent=2))
        return 0

    sort_label = "内存" if args.by_mem else "CPU"
    print(f"{BOLD}procx{RESET}  {DIM}top {min(len(procs), args.top)} by {sort_label}"
          + (f"，过滤: {args.filter}" if args.filter else "")
          + f"，共 {len(procs)} 个进程{RESET}")
    print()
    if args.tree:
        render_tree(procs, args.top, sort_key)
    else:
        render_flat(procs, args.top)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
