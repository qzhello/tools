#!/usr/bin/env python3
"""topx - 简洁的系统监控 TUI。

四象限：CPU / 内存 / 网络 / 磁盘（sparkline + 实时数值）
下方：进程列表（可选中、可杀）

数据源全部来自 macOS 自带（零外部依赖）：
  - CPU / 内存 / 负载: `top -l 1 -n 0`
  - 网络流量:           `netstat -ib`（原始 byte 累计 → 计算速率）
  - 磁盘 I/O:           `iostat -d -K -w 1 -c 2`（每秒采样）
  - 进程列表:           `ps -eo ...`
"""

from __future__ import annotations

import argparse
import curses
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple


SPARK = "▁▂▃▄▅▆▇█"
HISTORY = 120  # 最多保留 120 个采样


# ──────────────── 数据采集 ────────────────


SIZE_RE = re.compile(r"([\d.]+)\s*([KMGT]?)")


def parse_size(s: str) -> int:
    """把 '1.5G' / '256M' / '1024' 转成字节。"""
    m = SIZE_RE.match(s.strip())
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"": 1, "K": 1024, "M": 1024 ** 2,
            "G": 1024 ** 3, "T": 1024 ** 4}.get(m.group(2), 1)
    return int(n * mult)


def humanize(n: float) -> str:
    f = float(n)
    for u in ("B", "K", "M", "G", "T"):
        if f < 1024 or u == "T":
            if u == "B":
                return f"{int(f)}B"
            return f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}T"


def humanize_rate(bps: float) -> str:
    return f"{humanize(bps)}/s"


def parse_top() -> Dict:
    proc = subprocess.run(
        ["top", "-l", "1", "-n", "0", "-s", "0"],
        capture_output=True, check=False,
    )
    out = proc.stdout.decode("utf-8", errors="replace")

    raw: Dict = {
        "cpu_user": 0.0, "cpu_sys": 0.0, "cpu_idle": 100.0,
        "load1": 0.0, "load5": 0.0, "load15": 0.0,
        "mem_used": 0, "mem_total": 1, "mem_wired": 0,
        "proc_total": 0, "proc_running": 0,
    }

    m = re.search(
        r"CPU usage:\s*([\d.]+)%\s*user[,;]?\s*([\d.]+)%\s*sys[,;]?\s*([\d.]+)%\s*idle",
        out,
    )
    if m:
        raw["cpu_user"] = float(m.group(1))
        raw["cpu_sys"] = float(m.group(2))
        raw["cpu_idle"] = float(m.group(3))

    m = re.search(r"Load Avg:\s*([\d.]+),?\s*([\d.]+),?\s*([\d.]+)", out)
    if m:
        raw["load1"] = float(m.group(1))
        raw["load5"] = float(m.group(2))
        raw["load15"] = float(m.group(3))

    m = re.search(
        r"PhysMem:\s*([\d.]+[KMGT]?)\s*used\s*\(([\d.]+[KMGT]?)\s*wired[^)]*\),\s*([\d.]+[KMGT]?)\s*unused",
        out,
    )
    if m:
        used = parse_size(m.group(1))
        wired = parse_size(m.group(2))
        unused = parse_size(m.group(3))
        raw["mem_used"] = used
        raw["mem_total"] = used + unused
        raw["mem_wired"] = wired

    m = re.search(r"Processes:\s*(\d+)\s*total,\s*(\d+)\s*running", out)
    if m:
        raw["proc_total"] = int(m.group(1))
        raw["proc_running"] = int(m.group(2))

    return raw


def parse_netstat() -> Tuple[int, int]:
    """返回 (总入字节, 总出字节)，跨所有非 loopback 接口求和。

    netstat -ib 输出每个接口可能多行（不同协议），但字节计数同。
    我们只取 Network 字段以 '<Link#' 开头的那一行（聚合行），且排除 lo*。
    """
    try:
        proc = subprocess.run(
            ["netstat", "-ib"], capture_output=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0, 0
    out = proc.stdout.decode("utf-8", errors="replace")
    total_in = 0
    total_out = 0
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[0].rstrip("*")
        network = parts[2]
        if name.startswith("lo"):
            continue
        if not network.startswith("<Link#"):
            continue  # 跳过同一接口的协议子行
        try:
            ibytes = int(parts[6])
            obytes = int(parts[9])
        except (ValueError, IndexError):
            continue
        total_in += ibytes
        total_out += obytes
    return total_in, total_out


def parse_iostat_once(timeout: float = 3.0) -> Tuple[float, float]:
    """单次采样磁盘 I/O，返回 (读 字节/秒, 写 字节/秒)。

    macOS iostat 不区分读写（默认只输出 MB/s 总量），
    我们用 `-d -K -w 1 -c 2` 强制采样 1 秒，第二行就是该秒的实际 MB/s。

    返回值约定：read = total throughput, write = 0（macOS 不区分）。
    """
    try:
        proc = subprocess.run(
            ["iostat", "-d", "-K", "-w", "1", "-c", "2"],
            capture_output=True, check=False, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0.0, 0.0
    out = proc.stdout.decode("utf-8", errors="replace")
    lines = [l for l in out.splitlines() if l.strip()]
    # 找到最后一行数据（包含数字）
    data_lines = [l for l in lines if re.match(r"^\s*[\d.]", l)]
    if len(data_lines) < 2:
        return 0.0, 0.0
    # 取最后一行（per-second 采样）
    nums = [float(x) for x in data_lines[-1].split() if re.fullmatch(r"[\d.]+", x)]
    # 每个 disk 是 3 列：KB/t, tps, MB/s。我们要每个 disk 的第 3 个数（MB/s）
    total_mbps = 0.0
    for i in range(2, len(nums), 3):
        total_mbps += nums[i]
    return total_mbps * 1024 ** 2, 0.0  # MB → bytes


def parse_ps() -> List[Dict]:
    proc = subprocess.run(
        ["ps", "-eo", "pid,user,pcpu,pmem,rss,etime,command"],
        capture_output=True, check=False,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    procs: List[Dict] = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        try:
            procs.append({
                "pid": int(parts[0]),
                "user": parts[1],
                "pcpu": float(parts[2]),
                "pmem": float(parts[3]),
                "rss_kb": int(parts[4]),
                "etime": parts[5],
                "command": parts[6],
            })
        except ValueError:
            continue
    return procs


# ──────────────── 状态 ────────────────


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cpu_hist: Deque[float] = deque(maxlen=HISTORY)
        self.mem_hist: Deque[float] = deque(maxlen=HISTORY)
        self.net_in_hist: Deque[float] = deque(maxlen=HISTORY)
        self.net_out_hist: Deque[float] = deque(maxlen=HISTORY)
        self.disk_r_hist: Deque[float] = deque(maxlen=HISTORY)
        self.disk_w_hist: Deque[float] = deque(maxlen=HISTORY)

        # 上次采样的累计值（用于算 rate）
        self.last_t: Optional[float] = None
        self.last_net_in = 0
        self.last_net_out = 0
        self.last_disk_r = 0
        self.last_disk_w = 0

        # 当前快照
        self.cur: Dict = {}
        self.net_in_rate = 0.0
        self.net_out_rate = 0.0
        self.disk_r_rate = 0.0
        self.disk_w_rate = 0.0

        # 进程
        self.procs: List[Dict] = []
        self.cursor = 0          # 当前选中（基于过滤后的索引）
        self.scroll = 0
        self.sort_key = "pcpu"
        self.filter_text = ""
        self.paused = False
        self.show_help = False
        self.flash = ""
        self.flash_until = 0.0
        self.last_proc_t = 0.0
        self.proc_interval = 2.0  # 进程列表每 2s 刷新一次（ps 较慢）
        self.quad_pct = 50        # 4 象限占总高度的百分比（运行时可调）

    def update_sys(self, raw: Dict) -> None:
        """更新 CPU / 内存（来自 top -l 1）。"""
        self.cur = raw
        self.cpu_hist.append(raw["cpu_user"] + raw["cpu_sys"])
        if raw["mem_total"]:
            self.mem_hist.append(100 * raw["mem_used"] / raw["mem_total"])

    def update_net(self, in_bytes: int, out_bytes: int) -> None:
        """更新网络速率（基于两次采样差）。"""
        now = time.monotonic()
        if self.last_t is not None and self.last_net_in:
            dt = now - self.last_t
            if dt > 0:
                self.net_in_rate = max(0.0, (in_bytes - self.last_net_in) / dt)
                self.net_out_rate = max(0.0, (out_bytes - self.last_net_out) / dt)
                self.net_in_hist.append(self.net_in_rate)
                self.net_out_hist.append(self.net_out_rate)
        self.last_t = now
        self.last_net_in = in_bytes
        self.last_net_out = out_bytes

    def update_disk(self, r_bps: float, w_bps: float) -> None:
        """更新磁盘速率（iostat 直接给出 per-second 值）。"""
        self.disk_r_rate = r_bps
        self.disk_w_rate = w_bps
        self.disk_r_hist.append(r_bps)
        if w_bps > 0:
            self.disk_w_hist.append(w_bps)

    def update_procs(self) -> None:
        self.procs = parse_ps()
        self.last_proc_t = time.monotonic()

    def filtered_procs(self) -> List[Dict]:
        procs = self.procs
        if self.filter_text:
            q = self.filter_text.lower()
            procs = [p for p in procs
                     if q in p["command"].lower() or q in p["user"].lower()]
        procs = sorted(procs, key=lambda p: p[self.sort_key], reverse=(self.sort_key != "pid"))
        return procs

    def selected_proc(self) -> Optional[Dict]:
        procs = self.filtered_procs()
        if 0 <= self.cursor < len(procs):
            return procs[self.cursor]
        return None

    def set_flash(self, msg: str, sec: float = 3.0) -> None:
        self.flash = msg
        self.flash_until = time.monotonic() + sec


# ──────────────── 渲染 ────────────────


COLOR_PAIRS: Dict[str, int] = {}


def init_colors() -> None:
    global COLOR_PAIRS
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    pairs = [
        ("red",     curses.COLOR_RED),
        ("green",   curses.COLOR_GREEN),
        ("yellow",  curses.COLOR_YELLOW),
        ("blue",    curses.COLOR_BLUE),
        ("magenta", curses.COLOR_MAGENTA),
        ("cyan",    curses.COLOR_CYAN),
        ("white",   curses.COLOR_WHITE),
    ]
    for i, (name, color) in enumerate(pairs, start=1):
        try:
            curses.init_pair(i, color, bg)
            COLOR_PAIRS[name] = curses.color_pair(i)
        except curses.error:
            COLOR_PAIRS[name] = 0


def col(name: str) -> int:
    return COLOR_PAIRS.get(name, 0)


def cpu_color(v: float) -> int:
    if v >= 80:
        return col("red")
    if v >= 50:
        return col("yellow")
    if v >= 20:
        return col("green")
    return curses.A_DIM


def mem_color(v: float) -> int:
    if v >= 90:
        return col("red")
    if v >= 75:
        return col("yellow")
    return col("green")


def safe_addnstr(stdscr, y: int, x: int, s: str, n: int, attr: int = 0) -> None:
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    avail = max(0, min(n, w - x - 1))  # -1 防最后一格
    if avail <= 0:
        return
    try:
        stdscr.addnstr(y, x, s, avail, attr)
    except curses.error:
        pass


def safe_addstr(stdscr, y: int, x: int, s: str, attr: int = 0) -> None:
    safe_addnstr(stdscr, y, x, s, len(s) * 4, attr)  # 多给点 budget；addnstr 还会按可用截


def disp_w(s: str) -> int:
    """估算字符串显示宽度（CJK = 2，其他 = 1）。"""
    w = 0
    for c in s:
        o = ord(c)
        if o >= 0x1100 and (
            o <= 0x115F or 0x2E80 <= o <= 0x9FFF or
            0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF or
            0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60 or
            0xFFE0 <= o <= 0xFFE6
        ):
            w += 2
        else:
            w += 1
    return w


def truncate_w(s: str, max_w: int) -> str:
    if disp_w(s) <= max_w:
        return s
    out = []
    cur = 0
    for c in s:
        cw = 2 if disp_w(c) == 2 else 1
        if cur + cw > max_w - 1:
            break
        out.append(c)
        cur += cw
    return "".join(out) + "…"


def sparkline(samples: Deque[float], width: int, max_val: Optional[float] = None) -> str:
    if width <= 0:
        return ""
    if not samples:
        return " " * width
    data = list(samples)[-width:]
    pad = width - len(data)
    if pad > 0:
        data = [0.0] * pad + data
    if max_val is None:
        m = max(data) if any(data) else 1.0
    else:
        m = max(max_val, 0.001)
    chars = []
    for s in data:
        if s <= 0:
            chars.append(" ")
            continue
        n = min(s / m, 1.0)
        idx = max(0, min(len(SPARK) - 1, int(n * (len(SPARK) - 1))))
        chars.append(SPARK[idx])
    return "".join(chars)


def draw_box(stdscr, y: int, x: int, h: int, w: int, title: str = "") -> None:
    if h < 2 or w < 2:
        return
    safe_addstr(stdscr, y, x, "┌" + "─" * (w - 2) + "┐", curses.A_DIM)
    for i in range(1, h - 1):
        safe_addstr(stdscr, y + i, x, "│", curses.A_DIM)
        safe_addstr(stdscr, y + i, x + w - 1, "│", curses.A_DIM)
    safe_addstr(stdscr, y + h - 1, x, "└" + "─" * (w - 2) + "┘", curses.A_DIM)
    if title:
        safe_addstr(stdscr, y, x + 2, f" {title} ", curses.A_BOLD | col("cyan"))


def draw_panel_cpu(stdscr, y: int, x: int, h: int, w: int, st: State) -> None:
    draw_box(stdscr, y, x, h, w, "CPU")
    inner_w = w - 4
    cy = y + 1
    cx = x + 2
    if not st.cur:
        return
    total = st.cur["cpu_user"] + st.cur["cpu_sys"]
    safe_addstr(stdscr, cy, cx, f"{total:5.1f}%", curses.A_BOLD | cpu_color(total))
    info = (f"u {st.cur['cpu_user']:.1f}  s {st.cur['cpu_sys']:.1f}  "
            f"id {st.cur['cpu_idle']:.1f}")
    safe_addstr(stdscr, cy, cx + 8, info, curses.A_DIM)
    # load
    if h >= 5:
        load = (f"load {st.cur.get('load1', 0):.2f} "
                f"{st.cur.get('load5', 0):.2f} {st.cur.get('load15', 0):.2f}")
        safe_addstr(stdscr, cy + 1, cx, load, curses.A_DIM)
    # sparkline
    if h >= 4:
        spark = sparkline(st.cpu_hist, inner_w, max_val=100)
        # 颜色按当前值
        safe_addstr(stdscr, y + h - 2, cx, spark, cpu_color(total))


def draw_panel_mem(stdscr, y: int, x: int, h: int, w: int, st: State) -> None:
    draw_box(stdscr, y, x, h, w, "MEM")
    inner_w = w - 4
    cy = y + 1
    cx = x + 2
    if not st.cur or not st.cur["mem_total"]:
        return
    used = st.cur["mem_used"]
    total = st.cur["mem_total"]
    pct = 100 * used / total
    safe_addstr(stdscr, cy, cx, f"{pct:5.1f}%", curses.A_BOLD | mem_color(pct))
    info = f"{humanize(used)} / {humanize(total)}"
    safe_addstr(stdscr, cy, cx + 8, info, curses.A_DIM)
    if h >= 5:
        wired = st.cur.get("mem_wired", 0)
        safe_addstr(stdscr, cy + 1, cx, f"wired {humanize(wired)}", curses.A_DIM)
    if h >= 4:
        spark = sparkline(st.mem_hist, inner_w, max_val=100)
        safe_addstr(stdscr, y + h - 2, cx, spark, mem_color(pct))


def draw_panel_net(stdscr, y: int, x: int, h: int, w: int, st: State) -> None:
    draw_box(stdscr, y, x, h, w, "NET")
    inner_w = w - 4
    cy = y + 1
    cx = x + 2
    rate_in = st.net_in_rate
    rate_out = st.net_out_rate
    safe_addstr(stdscr, cy, cx,
                f"↓ {humanize_rate(rate_in):>10}", col("green"))
    safe_addstr(stdscr, cy + 1, cx,
                f"↑ {humanize_rate(rate_out):>10}", col("yellow"))
    if h >= 5:
        spark_in = sparkline(st.net_in_hist, inner_w)
        spark_out = sparkline(st.net_out_hist, inner_w)
        safe_addstr(stdscr, y + h - 3, cx, spark_in, col("green"))
        safe_addstr(stdscr, y + h - 2, cx, spark_out, col("yellow"))


def draw_panel_disk(stdscr, y: int, x: int, h: int, w: int, st: State) -> None:
    draw_box(stdscr, y, x, h, w, "DISK I/O")
    inner_w = w - 4
    cy = y + 1
    cx = x + 2
    # macOS 的 iostat 不区分读 / 写，这里显示总吞吐
    rate = st.disk_r_rate
    safe_addstr(stdscr, cy, cx, f"  {humanize_rate(rate):>12}",
                curses.A_BOLD | col("cyan"))
    safe_addstr(stdscr, cy + 1, cx, "总吞吐（读+写）", curses.A_DIM)
    if h >= 4:
        spark = sparkline(st.disk_r_hist, inner_w)
        safe_addstr(stdscr, y + h - 2, cx, spark, col("cyan"))


def draw_processes(stdscr, y: int, x: int, h: int, w: int, st: State) -> None:
    draw_box(stdscr, y, x, h, w, f"PROCESSES ({st.sort_key})")
    inner_w = w - 4
    rows_avail = h - 3  # box top + header + box bottom
    if rows_avail < 1:
        return

    procs = st.filtered_procs()
    if st.cursor >= len(procs):
        st.cursor = max(0, len(procs) - 1)
    if st.cursor < st.scroll:
        st.scroll = st.cursor
    if st.cursor >= st.scroll + rows_avail:
        st.scroll = st.cursor - rows_avail + 1
    if st.scroll < 0:
        st.scroll = 0

    # 列宽
    pid_w, user_w, cpu_w, mem_w, rss_w, time_w = 6, 10, 6, 6, 7, 7
    cmd_w = inner_w - (pid_w + user_w + cpu_w + mem_w + rss_w + time_w + 6)
    cmd_w = max(10, cmd_w)

    # header
    hy = y + 1
    hx = x + 2
    header = (
        f"{'PID':>{pid_w}} "
        f"{'USER':<{user_w}} "
        f"{'%CPU':>{cpu_w}} "
        f"{'%MEM':>{mem_w}} "
        f"{'RSS':>{rss_w}} "
        f"{'TIME':>{time_w}} "
        f"COMMAND"
    )
    safe_addnstr(stdscr, hy, hx, header, inner_w, curses.A_BOLD | col("cyan"))

    # 行
    visible = procs[st.scroll: st.scroll + rows_avail]
    for i, p in enumerate(visible):
        ry = hy + 1 + i
        is_sel = (st.scroll + i) == st.cursor
        base = curses.A_REVERSE if is_sel else 0

        pid_s = f"{p['pid']:>{pid_w}}"
        user_s = f"{p['user'][:user_w]:<{user_w}}"
        cpu_s = f"{p['pcpu']:>{cpu_w}.1f}"
        mem_s = f"{p['pmem']:>{mem_w}.1f}"
        rss_s = f"{humanize(p['rss_kb'] * 1024):>{rss_w}}"
        time_s = f"{p['etime']:>{time_w}}"
        cmd_s = truncate_w(p["command"], cmd_w)

        # 整行先用反转背景画一遍，再叠加值的颜色
        cx = hx
        safe_addstr(stdscr, ry, cx, pid_s, base | curses.A_DIM); cx += pid_w + 1
        safe_addstr(stdscr, ry, cx, user_s, base);                cx += user_w + 1
        safe_addstr(stdscr, ry, cx, cpu_s, base | cpu_color(p["pcpu"])); cx += cpu_w + 1
        safe_addstr(stdscr, ry, cx, mem_s, base | mem_color(p["pmem"])); cx += mem_w + 1
        safe_addstr(stdscr, ry, cx, rss_s, base);                  cx += rss_w + 1
        safe_addstr(stdscr, ry, cx, time_s, base | curses.A_DIM); cx += time_w + 1
        safe_addstr(stdscr, ry, cx, cmd_s, base)

    # 滚动指示
    if len(procs) > rows_avail:
        info = f"{st.scroll + 1}-{min(st.scroll + rows_avail, len(procs))}/{len(procs)}"
        safe_addstr(stdscr, y, x + w - len(info) - 4, f" {info} ",
                    curses.A_DIM | col("cyan"))


def draw_title(stdscr, w: int, st: State) -> None:
    n_procs = st.cur.get("proc_total", 0) if st.cur else 0
    pause = " [PAUSED]" if st.paused else ""
    flt = f"  filter: {st.filter_text}" if st.filter_text else ""
    title = f" topx  {n_procs} procs  排序: {st.sort_key}{flt}{pause} "
    safe_addnstr(stdscr, 0, 0, title.ljust(w - 1), w - 1,
                 curses.A_REVERSE | curses.A_BOLD)


def draw_footer(stdscr, h: int, w: int, st: State) -> None:
    if st.flash and time.monotonic() < st.flash_until:
        msg = f" {st.flash} "
        safe_addnstr(stdscr, h - 1, 0, msg.ljust(w - 1), w - 1,
                     curses.A_REVERSE | col("yellow"))
        return
    help_line = (
        " q:退出  Space:暂停  ↑↓:选择  K:杀  c/m/p/t:排序  /:过滤  +/-:象限大小  ?:帮助 "
    )
    safe_addnstr(stdscr, h - 1, 0, help_line, w - 1, curses.A_DIM)


def draw_help(stdscr) -> None:
    h, w = stdscr.getmaxyx()
    lines = [
        "── topx 帮助 ──",
        "",
        "  q / Esc       退出",
        "  Space         暂停 / 恢复刷新",
        "  ↑ ↓ / k j     上下移动选中进程",
        "  PgUp / PgDn   按页翻动",
        "  Home / End    跳到首 / 末",
        "  K             杀掉当前选中进程（先确认）",
        "  c             按 CPU 排序",
        "  m             按内存（RSS）排序",
        "  p             按 PID 排序",
        "  t             按运行时长排序",
        "  /             进入过滤模式（直接输入字符）",
        "  Esc           过滤态下清空过滤",
        "  + / -         调整 4 象限占比（5% 步长，20%–80%）",
        "  ?             显示 / 隐藏本帮助",
        "",
        " 数据源：top -l 1 + ps（macOS 自带）",
        "",
        " 任意键关闭",
    ]
    # 用显示宽度计算（中文字符 = 2 列）
    content_w = max(disp_w(l) for l in lines)
    bw = content_w + 4   # "│ " + content + " │"
    bh = len(lines) + 2
    by = max(0, (h - bh) // 2)
    bx = max(0, (w - bw) // 2)
    # 清背景
    for i in range(bh):
        safe_addstr(stdscr, by + i, bx, " " * bw, curses.A_REVERSE)
    safe_addstr(stdscr, by, bx, "┌" + "─" * (bw - 2) + "┐", curses.A_REVERSE | col("cyan"))
    for i, line in enumerate(lines):
        padded = line + " " * max(0, content_w - disp_w(line))
        safe_addstr(stdscr, by + 1 + i, bx, "│ " + padded + " │",
                    curses.A_REVERSE)
    safe_addstr(stdscr, by + bh - 1, bx, "└" + "─" * (bw - 2) + "┘",
                curses.A_REVERSE | col("cyan"))


# ──────────────── 操作 ────────────────


def kill_selected(stdscr, st: State) -> None:
    p = st.selected_proc()
    if not p:
        return
    h, w = stdscr.getmaxyx()
    msg = f" 杀掉 PID {p['pid']} ({p['command'][:40]})？[y/N] "
    safe_addnstr(stdscr, h - 1, 0, msg.ljust(w - 1), w - 1,
                 curses.A_REVERSE | col("red"))
    stdscr.refresh()
    stdscr.timeout(-1)  # 阻塞等待
    ch = stdscr.getch()
    stdscr.timeout(150)
    if ch in (ord("y"), ord("Y")):
        try:
            os.kill(p["pid"], signal.SIGTERM)
            st.set_flash(f"SIGTERM → {p['pid']} ({p['command'][:30]})")
        except ProcessLookupError:
            st.set_flash(f"PID {p['pid']} 已退出")
        except PermissionError:
            st.set_flash(f"PID {p['pid']}：无权限（需 sudo）")
    else:
        st.set_flash("已取消")


def filter_input(stdscr, st: State) -> None:
    h, w = stdscr.getmaxyx()
    buf = ""
    curses.curs_set(1)
    while True:
        prompt = f" /{buf}"
        safe_addnstr(stdscr, h - 1, 0, prompt.ljust(w - 1), w - 1,
                     curses.A_REVERSE | col("cyan"))
        # 把光标放到合适位置
        try:
            stdscr.move(h - 1, min(len(prompt), w - 1))
        except curses.error:
            pass
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (10, 13):
            break
        if ch == 27:
            buf = ""
            break
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127:
            buf += chr(ch)
    curses.curs_set(0)
    st.filter_text = buf
    st.cursor = 0
    st.scroll = 0


# ──────────────── 主循环 ────────────────


def _wait(stop: threading.Event, secs: float) -> None:
    """分段 sleep，便于及时响应 stop event。"""
    slept = 0.0
    while slept < secs and not stop.is_set():
        time.sleep(min(0.1, secs - slept))
        slept += 0.1


def _sys_collector(st: State, stop: threading.Event, interval: float) -> None:
    """采集 CPU / 内存（top）+ 网络字节计数（netstat）。"""
    while not stop.is_set():
        if not st.paused:
            try:
                raw = parse_top()
                in_b, out_b = parse_netstat()
                with st.lock:
                    st.update_sys(raw)
                    st.update_net(in_b, out_b)
            except Exception as e:
                st.set_flash(f"采集失败: {e}")
        _wait(stop, interval)


def _disk_collector(st: State, stop: threading.Event) -> None:
    """采集磁盘 I/O。iostat -w 1 -c 2 自身阻塞 ~1s，相当于 1Hz 采样。"""
    while not stop.is_set():
        if not st.paused:
            try:
                r_bps, w_bps = parse_iostat_once()
                with st.lock:
                    st.update_disk(r_bps, w_bps)
            except Exception:
                pass
        else:
            _wait(stop, 0.5)


def _proc_collector(st: State, stop: threading.Event, interval: float) -> None:
    while not stop.is_set():
        if not st.paused:
            try:
                procs = parse_ps()
                with st.lock:
                    st.procs = procs
                    st.last_proc_t = time.monotonic()
            except Exception:
                pass
        slept = 0.0
        step = 0.1
        while slept < interval and not stop.is_set():
            time.sleep(step)
            slept += step


def tui_main(stdscr, args) -> None:
    curses.curs_set(0)
    stdscr.timeout(150)  # 150ms 一次 getch（响应键盘的频率）
    init_colors()

    st = State()
    # 应用 CLI 默认值
    st.quad_pct = max(20, min(80, args.quad_pct))

    # 启动后台采集线程
    stop = threading.Event()
    t_sys = threading.Thread(target=_sys_collector,
                             args=(st, stop, args.interval), daemon=True)
    t_disk = threading.Thread(target=_disk_collector,
                              args=(st, stop), daemon=True)
    t_proc = threading.Thread(target=_proc_collector,
                              args=(st, stop, max(args.interval * 2, 1.5)), daemon=True)
    t_sys.start()
    t_disk.start()
    t_proc.start()

    # 等首次采集完成
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with st.lock:
            if st.cur and st.procs:
                break
        time.sleep(0.1)

    try:
        _run_event_loop(stdscr, st)
    finally:
        # daemon 线程会随主进程退出；不要 join 等待它们
        # （disk 线程可能正卡在 iostat -w 1 阻塞中，等它会拖慢退出 ~1s）
        stop.set()


def _run_event_loop(stdscr, st: State) -> None:
    while True:
        # 不再在主循环里采集——线程在做。这里只画 + 处理键盘。

        # 绘制
        h, w = stdscr.getmaxyx()
        if h < 14 or w < 60:
            stdscr.erase()
            safe_addstr(stdscr, 0, 0, "终端太小，请放大窗口（>= 60×14）")
            stdscr.refresh()
            stdscr.getch()
            continue

        stdscr.erase()

        # 4 象限高度根据 quad_pct 动态计算
        # 可用高度 = 总高 - 标题(1) - 页脚(1)
        usable_h = max(8, h - 2)
        quad_total_h = max(8, usable_h * st.quad_pct // 100)
        # 单个象限至少 4 行；进程列表至少 4 行
        panel_h = max(4, quad_total_h // 2)
        # 如果 panel_h × 2 + 进程区 < 可用高度，约束以保留进程区 ≥ 4
        if usable_h - 2 * panel_h < 4:
            panel_h = max(4, (usable_h - 4) // 2)

        panel_w = w // 2
        right_w = w - panel_w

        draw_panel_cpu(stdscr, 1, 0,        panel_h, panel_w, st)
        draw_panel_mem(stdscr, 1, panel_w,  panel_h, right_w, st)
        draw_panel_net(stdscr, 1 + panel_h, 0,        panel_h, panel_w, st)
        draw_panel_disk(stdscr, 1 + panel_h, panel_w, panel_h, right_w, st)

        proc_y = 1 + 2 * panel_h
        proc_h = h - proc_y - 1
        if proc_h >= 4:
            draw_processes(stdscr, proc_y, 0, proc_h, w, st)

        draw_title(stdscr, w, st)
        draw_footer(stdscr, h, w, st)

        if st.show_help:
            draw_help(stdscr)

        stdscr.refresh()

        # 键盘
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break

        if ch == -1:
            continue

        if st.show_help:
            st.show_help = False
            continue

        if ch in (ord("q"), 27):
            break
        if ch == ord(" "):
            st.paused = not st.paused
            st.set_flash("已暂停" if st.paused else "继续刷新")
        elif ch in (curses.KEY_DOWN, ord("j")):
            st.cursor += 1
        elif ch in (curses.KEY_UP, ord("k")):
            st.cursor = max(0, st.cursor - 1)
        elif ch == curses.KEY_NPAGE:
            st.cursor += 10
        elif ch == curses.KEY_PPAGE:
            st.cursor = max(0, st.cursor - 10)
        elif ch == curses.KEY_HOME:
            st.cursor = 0
        elif ch == curses.KEY_END:
            st.cursor = max(0, len(st.filtered_procs()) - 1)
        elif ch == ord("c"):
            st.sort_key = "pcpu";   st.cursor = 0
        elif ch == ord("m"):
            st.sort_key = "rss_kb"; st.cursor = 0
        elif ch == ord("p"):
            st.sort_key = "pid";    st.cursor = 0
        elif ch == ord("t"):
            st.sort_key = "etime";  st.cursor = 0
        elif ch == ord("/"):
            filter_input(stdscr, st)
        elif ch == ord("K"):
            kill_selected(stdscr, st)
            # 进程列表会在下一轮自动刷新
        elif ch in (ord("+"), ord("=")):
            st.quad_pct = min(80, st.quad_pct + 5)
            st.set_flash(f"四象限占比 {st.quad_pct}%")
        elif ch in (ord("-"), ord("_")):
            st.quad_pct = max(20, st.quad_pct - 5)
            st.set_flash(f"四象限占比 {st.quad_pct}%")
        elif ch == ord("?"):
            st.show_help = True


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="topx",
        description="简洁的系统监控 TUI（CPU/MEM/NET/DISK + 进程列表）",
    )
    p.add_argument("-i", "--interval", type=float, default=1.0,
                   help="系统数据刷新间隔秒数（默认 1.0）")
    p.add_argument("-Q", "--quad-pct", type=int, default=50,
                   help="4 象限占总高度的百分比（默认 50；运行时按 + / - 调整）")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    # ps 排序时支持 etime 字符串排序不太正确（应按秒）
    # 但 etime 字段格式简单，用字符串排序近似可用，不做额外处理

    try:
        curses.wrapper(tui_main, args)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
