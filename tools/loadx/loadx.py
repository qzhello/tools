#!/usr/bin/env python3
"""loadx - 一句话告诉你机器现在累在哪。

不像 topx 全景 TUI，loadx 一次采样、一句话结论：
  - 找出最大瓶颈（CPU / 内存 / 网络 / 磁盘 / 电池 / 散热）
  - 每项给当前指标 + Top 3 消耗者
  - 给一条简短建议

采样源（macOS）：
  top -l 2 -n N   每进程 CPU/MEM/POWER（取 -l 2 第二段才是真实利用率）
  vm_stat         内存压力 + swap
  pmset -g batt   电池/电源
  netstat -ib     网卡累计字节，两次采样取差
  iostat -d -w 1 -c 2  磁盘每秒
  sysctl          硬件型号
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("LOADX_FORCE_COLOR") or sys.stdout.isatty())
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


# ---------- 数据采样 ----------

@dataclass
class Proc:
    pid: int
    name: str
    cpu: float = 0.0       # %
    mem_kb: int = 0
    power: float = 0.0     # 瓦/相对单位


@dataclass
class TopSnap:
    cpu_user: float = 0.0
    cpu_sys: float = 0.0
    cpu_idle: float = 0.0
    phys_total_b: int = 0
    phys_used_b: int = 0
    phys_unused_b: int = 0
    wired_b: int = 0
    compressor_b: int = 0
    procs: List[Proc] = field(default_factory=list)


_SIZE_RE = re.compile(r"^([\d.]+)\s*([KMGT])?$", re.IGNORECASE)


def _to_bytes(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    m = _SIZE_RE.match(s)
    if not m:
        return 0
    n = float(m.group(1))
    unit = (m.group(2) or "").upper()
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[unit]
    return int(n * mult)


def _short_name(cmd: str, max_len: int = 24) -> str:
    """top 的 COMMAND 列截断到 16 字符；尽量给个有意义的名字。"""
    name = cmd.strip()
    if len(name) > max_len:
        name = name[: max_len - 1] + "…"
    return name


def sample_top(n_procs: int = 50) -> TopSnap:
    """跑两段 top（间隔 1s），用第二段才能拿到真实 CPU%。"""
    try:
        # -s 0 让两次采样紧挨着（默认 1s 间隔），CPU% 精度略降但快一倍
        out = subprocess.run(
            ["top", "-l", "2", "-s", "0", "-n", str(n_procs),
             "-stats", "pid,command,cpu,mem,power",
             "-ncols", "5"],
            capture_output=True, check=False, timeout=8,
        ).stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return TopSnap()

    snap = TopSnap()
    # 切两段：找两次 "Processes:" 之间
    parts = out.split("\nProcesses:")
    raw = "Processes:" + parts[-1] if len(parts) > 1 else out

    for line in raw.splitlines():
        if line.startswith("CPU usage:"):
            m = re.search(r"([\d.]+)%\s*user.*?([\d.]+)%\s*sys.*?([\d.]+)%\s*idle", line)
            if m:
                snap.cpu_user = float(m.group(1))
                snap.cpu_sys = float(m.group(2))
                snap.cpu_idle = float(m.group(3))
        elif line.startswith("PhysMem:"):
            # PhysMem: 63G used (6017M wired, 28G compressor), 78M unused.
            m = re.search(r"([\d.]+[KMGT]?)\s*used\s*\(([\d.]+[KMGT]?)\s*wired,\s*([\d.]+[KMGT]?)\s*compressor\),\s*([\d.]+[KMGT]?)\s*unused", line)
            if m:
                snap.phys_used_b = _to_bytes(m.group(1))
                snap.wired_b = _to_bytes(m.group(2))
                snap.compressor_b = _to_bytes(m.group(3))
                snap.phys_unused_b = _to_bytes(m.group(4))
                snap.phys_total_b = snap.phys_used_b + snap.phys_unused_b

    # 进程列表：第二段的进程数据才是 1s 内真实 CPU%
    in_proc_section = False
    seen_header = 0
    for line in raw.splitlines():
        if line.startswith("PID") and "COMMAND" in line:
            seen_header += 1
            in_proc_section = True
            continue
        if not in_proc_section:
            continue
        if not line.strip():
            in_proc_section = False
            continue
        # 列：pid command cpu mem power
        # 注意 command 可能含空格，按位置切
        # top 输出固定列宽：pid 7 char, command 17 char (含尾空格), cpu, mem, power
        m = re.match(r"^(\d+)\s+(.{1,16}?)\s+([\d.]+)\s+(\S+)\s+([\d.]+)\s*$", line)
        if not m:
            continue
        pid = int(m.group(1))
        name = m.group(2).strip()
        cpu = float(m.group(3))
        mem_b = _to_bytes(m.group(4))
        power = float(m.group(5))
        snap.procs.append(Proc(pid=pid, name=name, cpu=cpu, mem_kb=mem_b // 1024, power=power))

    return snap


def sample_vm_stat() -> Dict[str, int]:
    """返回页数（不是字节）。"""
    try:
        out = subprocess.run(
            ["vm_stat"], capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    pages: Dict[str, int] = {}
    for line in out.splitlines():
        m = re.match(r"^(.+?):\s+(\d+)\.?\s*$", line)
        if not m:
            continue
        key = m.group(1).strip().strip('"')
        pages[key] = int(m.group(2))
    return pages


def sample_swap() -> Tuple[int, int]:
    """sysctl vm.swapusage → (used_b, total_b)"""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"],
            capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (0, 0)
    # total = 2048.00M  used = 1234.50M  free = ...
    m_total = re.search(r"total\s*=\s*([\d.]+)([KMGT])", out)
    m_used = re.search(r"used\s*=\s*([\d.]+)([KMGT])", out)
    total = _to_bytes(f"{m_total.group(1)}{m_total.group(2)}") if m_total else 0
    used = _to_bytes(f"{m_used.group(1)}{m_used.group(2)}") if m_used else 0
    return (used, total)


@dataclass
class NetSnap:
    in_bps: float = 0.0
    out_bps: float = 0.0


def sample_net(interval: float = 1.0) -> NetSnap:
    """两次 netstat -ib 取差。**按 interface 分别求差**，避免接口新增/重启时
    把整个生命周期累计当作 1s 流量；单接口异常大的 delta 也直接丢弃。"""
    def _read() -> Dict[str, Tuple[int, int]]:
        try:
            out = subprocess.run(
                ["netstat", "-ib"], capture_output=True, check=False, timeout=3,
            ).stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {}
        seen: Dict[str, Tuple[int, int]] = {}
        for line in out.splitlines()[1:]:
            cols = line.split()
            if len(cols) < 10:
                continue
            name, _mtu, network = cols[0], cols[1], cols[2]
            if name in seen or name.startswith("lo"):
                continue
            # 仅取链路级行（每个接口的第一行）；避免 IPv4 / IPv6 别名行重复计数
            if not network.startswith("<Link"):
                continue
            # Link 行有时没有 MAC 地址（比如 utun*），列就少一列。简单识别：
            # 如果 cols[3] 不是 MAC 形式（不含冒号且不是数字），按 9 列布局；否则 10 列
            try:
                if ":" in cols[3] or cols[3].count("-") >= 2:
                    # 有 Address：Ibytes=cols[6] Obytes=cols[9]
                    in_b = int(cols[6]); out_b = int(cols[9])
                else:
                    # 无 Address：Ibytes=cols[5] Obytes=cols[8]
                    in_b = int(cols[5]); out_b = int(cols[8])
            except (ValueError, IndexError):
                continue
            seen[name] = (in_b, out_b)
        return seen

    a = _read()
    time.sleep(interval)
    b = _read()

    # 单接口最大合理 delta：80Gbps = 10 GB/s，按 interval 放宽；超过认为是新启动/计数器重置
    max_delta = int(10 * 1024**3 * interval)

    in_total = out_total = 0
    for name in set(a) & set(b):  # 只算两次都出现的接口
        a_in, a_out = a[name]
        b_in, b_out = b[name]
        d_in = b_in - a_in
        d_out = b_out - a_out
        if 0 <= d_in <= max_delta:
            in_total += d_in
        if 0 <= d_out <= max_delta:
            out_total += d_out

    snap = NetSnap()
    snap.in_bps = in_total / interval
    snap.out_bps = out_total / interval
    return snap


@dataclass
class DiskSnap:
    bps: float = 0.0


def sample_disk(timeout: float = 3.0) -> DiskSnap:
    """iostat -d -K -w 1 -c 2 → 第二行是 1s 内的 MB/s。"""
    try:
        out = subprocess.run(
            ["iostat", "-d", "-K", "-w", "1", "-c", "2"],
            capture_output=True, check=False, timeout=timeout,
        ).stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return DiskSnap()
    lines = [l for l in out.splitlines() if l.strip()]
    if len(lines) < 3:
        return DiskSnap()
    # 倒数第 1 行是 1s 采样行；每磁盘 3 列 (KB/t tps MB/s)
    parts = lines[-1].split()
    mb_total = 0.0
    # 每三列一组，取第三列
    for i in range(2, len(parts), 3):
        try:
            mb_total += float(parts[i])
        except (ValueError, IndexError):
            pass
    snap = DiskSnap()
    snap.bps = mb_total * 1024 * 1024
    return snap


@dataclass
class BatterySnap:
    on_battery: bool = False
    pct: int = 0
    state: str = "未知"     # charged / charging / discharging
    time_left: str = ""
    ac_watts: int = 0       # 估算
    discharge_w: float = 0.0  # 放电功率


def sample_battery() -> Optional[BatterySnap]:
    try:
        out = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    snap = BatterySnap()
    snap.on_battery = "Battery Power" in out
    m = re.search(r"(\d+)%;\s*(\S+)(?:;\s*([\d:]+)\s*remaining)?", out)
    if m:
        snap.pct = int(m.group(1))
        snap.state = m.group(2).strip()
        snap.time_left = m.group(3) or ""

    # 用 ioreg 拿放电瓦数
    try:
        out2 = subprocess.run(
            ["ioreg", "-rn", "AppleSmartBattery"],
            capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
        m_amp = re.search(r'"Amperage"\s*=\s*(-?\d+)', out2)
        m_volt = re.search(r'"Voltage"\s*=\s*(\d+)', out2)
        if m_amp and m_volt:
            amp_ma = int(m_amp.group(1))
            volt_mv = int(m_volt.group(1))
            watts = abs(amp_ma) * volt_mv / 1_000_000.0
            snap.discharge_w = watts
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return snap


@dataclass
class HwInfo:
    model: str = ""
    ncpu: int = 0
    mem_total_b: int = 0


def sample_hw() -> HwInfo:
    info = HwInfo()
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.ncpu", "hw.memsize"],
            capture_output=True, check=False, timeout=2,
        ).stdout.decode("utf-8", errors="replace").strip().splitlines()
        if len(out) >= 2:
            info.ncpu = int(out[0])
            info.mem_total_b = int(out[1])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    # 友好型号名
    try:
        model = subprocess.run(
            ["sysctl", "-n", "hw.model"],
            capture_output=True, check=False, timeout=2,
        ).stdout.decode("utf-8", errors="replace").strip()
        info.model = model
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return info


# ---------- 评估 ----------

def fmt_bytes(b: float, per_sec: bool = False) -> str:
    units = ["B", "K", "M", "G", "T"]
    n = float(b)
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    s = f"{n:.1f}{units[i]}" if i > 0 else f"{int(n)}{units[i]}"
    return s + "/s" if per_sec else s


def severity_color(level: str) -> str:
    return {"ok": GREEN, "warn": YELLOW, "high": RED}.get(level, "")


@dataclass
class Verdict:
    name: str          # CPU / 内存 / 网络 / 磁盘 / 电池
    level: str         # ok / warn / high
    headline: str      # 一句话主指标
    detail: str        # top 消耗者
    score: float = 0.0 # 用于排序谁是最大瓶颈


def assess_cpu(snap: TopSnap, hw: HwInfo) -> Verdict:
    used = 100 - snap.cpu_idle
    if used >= 80:
        level = "high"
    elif used >= 50:
        level = "warn"
    else:
        level = "ok"
    headline = f"{used:.0f}%  ({snap.cpu_user:.0f}% 用户 + {snap.cpu_sys:.0f}% 系统)"
    if hw.ncpu:
        headline += f"  ·  {hw.ncpu} 核"
    top3 = sorted(snap.procs, key=lambda p: -p.cpu)[:3]
    top3 = [p for p in top3 if p.cpu > 0.5]
    detail = "  ".join(f"{p.name} {p.cpu:.0f}%" for p in top3) if top3 else "(空闲)"
    return Verdict("CPU", level, headline, detail, score=used)


def assess_mem(snap: TopSnap, vm: Dict[str, int], swap_used: int, swap_total: int) -> Verdict:
    if not snap.phys_total_b:
        return Verdict("内存", "ok", "无数据", "")
    used_pct = snap.phys_used_b / snap.phys_total_b * 100
    # 内存压力：compressor + swap 使用都算
    swap_g = swap_used / 1024**3
    pressure_high = swap_g > 1 or used_pct >= 90
    if pressure_high:
        level = "high"
    elif used_pct >= 75 or swap_g > 0.1:
        level = "warn"
    else:
        level = "ok"
    headline = f"{fmt_bytes(snap.phys_used_b)} / {fmt_bytes(snap.phys_total_b)}  ({used_pct:.0f}%)"
    if swap_g > 0.05:
        headline += f"  ·  swap {fmt_bytes(swap_used)}"
    top3 = sorted(snap.procs, key=lambda p: -p.mem_kb)[:3]
    detail = "  ".join(f"{p.name} {fmt_bytes(p.mem_kb * 1024)}" for p in top3) if top3 else ""
    score = used_pct + (swap_g * 10)  # swap 加权
    return Verdict("内存", level, headline, detail, score=score)


def assess_net(snap: NetSnap) -> Verdict:
    total = snap.in_bps + snap.out_bps
    mb = total / (1024**2)
    if mb >= 50:
        level = "high"
    elif mb >= 5:
        level = "warn"
    else:
        level = "ok"
    headline = f"↓ {fmt_bytes(snap.in_bps, True)}  ↑ {fmt_bytes(snap.out_bps, True)}"
    detail = ""  # macOS 上拿 per-process 网络要 sudo nettop，跳过
    return Verdict("网络", level, headline, detail, score=mb)


def assess_disk(snap: DiskSnap) -> Verdict:
    mb = snap.bps / (1024**2)
    if mb >= 200:
        level = "high"
    elif mb >= 30:
        level = "warn"
    else:
        level = "ok"
    headline = f"{fmt_bytes(snap.bps, True)}"
    return Verdict("磁盘", level, headline, "", score=mb / 5)  # disk 权重小一点


def assess_battery(snap: Optional[BatterySnap]) -> Optional[Verdict]:
    if snap is None or snap.pct == 0:
        return None
    if snap.on_battery:
        if snap.pct < 15:
            level = "high"
            headline = f"{snap.pct}%  ·  电池供电  ·  剩 {snap.time_left or '?'}  ·  耗 {snap.discharge_w:.0f}W"
        elif snap.discharge_w > 25:
            level = "warn"
            headline = f"{snap.pct}%  ·  电池供电  ·  耗 {snap.discharge_w:.0f}W (高)"
        else:
            level = "ok"
            headline = f"{snap.pct}%  ·  电池供电  ·  耗 {snap.discharge_w:.0f}W  ·  剩 {snap.time_left or '估算中'}"
    else:
        if snap.state == "charged":
            level = "ok"
            headline = f"{snap.pct}%  ·  AC 已充满"
        else:
            level = "ok"
            headline = f"{snap.pct}%  ·  AC 充电中"
    return Verdict("电池", level, headline, "", score=0)


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


_BAR_FILL = "█"
_BAR_EMPTY = "░"
# 亚像素：1/8 步进
_BAR_PARTIALS = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
# Sparkline：每个字符 = 一个采样
_SPARK = "▁▂▃▄▅▆▇█"


def _bar(ratio: float, width: int, color: str = "") -> str:
    """0..1 → 亚像素精度的着色条形图。"""
    ratio = max(0.0, min(1.0, ratio))
    cells = ratio * width
    full = int(cells)
    frac = cells - full
    partial = _BAR_PARTIALS[int(frac * 8)] if frac > 0 and full < width else ""
    empty_w = width - full - (1 if partial else 0)
    out = color + _BAR_FILL * full + partial + RESET
    out += DIM + _BAR_EMPTY * empty_w + RESET
    return out


def _stack_bar(parts: List[Tuple[float, str]], width: int) -> str:
    """堆叠条：parts = [(ratio, color), ...]，所有 ratio 加起来 ≤ 1。
    最后一段如果未填满，余下用 dim 空白填充。"""
    cells: List[Tuple[int, str]] = []
    used = 0.0
    used_cells = 0
    for ratio, color in parts:
        ratio = max(0.0, min(1.0 - used, ratio))
        seg_cells = int(round(ratio * width))
        if used_cells + seg_cells > width:
            seg_cells = width - used_cells
        if seg_cells > 0:
            cells.append((seg_cells, color))
            used_cells += seg_cells
        used += ratio
    out = ""
    for n, color in cells:
        out += f"{color}{_BAR_FILL * n}{RESET}"
    if used_cells < width:
        out += f"{DIM}{_BAR_EMPTY * (width - used_cells)}{RESET}"
    return out


def _sparkline(values: List[float], max_v: float = 1.0) -> str:
    """0..max_v 序列 → ▁▂▃▄▅▆▇█ 字符串。"""
    if not values:
        return ""
    out = []
    for v in values:
        ratio = max(0.0, min(1.0, v / max_v if max_v > 0 else 0))
        idx = int(ratio * (len(_SPARK) - 1))
        out.append(_SPARK[idx])
    return "".join(out)


def _level_color(level: str) -> str:
    return {"ok": GREEN, "warn": YELLOW, "high": RED}.get(level, "")


def _level_sym(level: str) -> str:
    return {"ok": "✓", "warn": "⚠", "high": "✗"}.get(level, "·")


def render(
    verdicts: List[Verdict],
    hw: HwInfo,
    snap: TopSnap,
    swap_used: int,
    net: "NetSnap",
    disk: "DiskSnap",
    bat: Optional["BatterySnap"],
    history: Optional[Dict[str, List[float]]] = None,
) -> None:
    # 头部
    title = f"{BOLD}{CYAN}loadx{RESET}"
    if hw.model:
        title += f"  {DIM}{hw.model}{RESET}"
    print(title)

    # 一句话结论
    candidates = [v for v in verdicts if v.level != "ok"]
    if candidates:
        worst = max(candidates, key=lambda v: v.score)
        color = _level_color(worst.level)
        sym = _level_sym(worst.level)
        print(f"\n{BOLD}瓶颈{RESET}  {color}{sym} {worst.name}{RESET}  {worst.headline}")
    else:
        print(f"\n{GREEN}✓ 整体健康，没看到瓶颈{RESET}")
    print()

    name_w = max(_disp_w(v.name) for v in verdicts)
    bar_w = 30
    proc_bar_w = 20
    proc_name_w = 18

    for v in verdicts:
        color = _level_color(v.level)
        sym = _level_sym(v.level)
        name_padded = _ljust_w(v.name, name_w)

        # 主条按指标定制（堆叠/普通）
        bar = _main_bar(v, snap, net, disk, bat, swap_used, bar_w)

        # sparkline（来自历史）
        spark = ""
        if history:
            key_map = {"CPU": "cpu", "内存": "mem", "网络": "net", "磁盘": "disk", "电池": "bat"}
            key = key_map.get(v.name)
            if key and history.get(key) and len(history[key]) >= 2:
                spark = f"  {color}{_sparkline(history[key], 1.0)}{RESET}"

        print(f"  {color}{sym}{RESET}  {BOLD}{name_padded}{RESET}  {bar}{spark}  {v.headline}")

        # 内存的图例
        if v.name == "内存" and snap.phys_total_b:
            wired = snap.wired_b / snap.phys_total_b
            comp = snap.compressor_b / snap.phys_total_b
            other = max(0, (snap.phys_used_b - snap.wired_b - snap.compressor_b) / snap.phys_total_b)
            free = snap.phys_unused_b / snap.phys_total_b
            legend = (
                f"{RED}■{RESET} 内核 {wired*100:.0f}%  "
                f"{YELLOW}■{RESET} 压缩 {comp*100:.0f}%  "
                f"{CYAN}■{RESET} 应用 {other*100:.0f}%  "
                f"{DIM}■ 空闲 {free*100:.0f}%{RESET}"
            )
            print(f"     {' ' * name_w}  {legend}")

        # Top 3 进程子条
        if v.name == "CPU":
            top = sorted(snap.procs, key=lambda p: -p.cpu)[:3]
            top = [p for p in top if p.cpu > 0.5]
            for p in top:
                pname = _ljust_w(_short_name(p.name, proc_name_w), proc_name_w)
                pbar = _bar(p.cpu / 100, proc_bar_w, _proc_color(p.cpu, 80, 30))
                print(f"     {' ' * name_w}  {DIM}▏{RESET} {pname} {pbar}  {p.cpu:.0f}%")
        elif v.name == "内存" and snap.phys_total_b:
            top = sorted(snap.procs, key=lambda p: -p.mem_kb)[:3]
            top = [p for p in top if p.mem_kb > 0]
            max_mem = top[0].mem_kb * 1024 if top else 1
            for p in top:
                mb = p.mem_kb * 1024
                pname = _ljust_w(_short_name(p.name, proc_name_w), proc_name_w)
                pbar = _bar(mb / max_mem, proc_bar_w, MAG)
                print(f"     {' ' * name_w}  {DIM}▏{RESET} {pname} {pbar}  {fmt_bytes(mb)}")

    # 建议
    tips = _suggest(verdicts)
    if tips:
        print()
        for t in tips:
            print(f"  {YELLOW}→{RESET} {t}")


def _main_bar(
    v: Verdict,
    snap: TopSnap,
    net: "NetSnap",
    disk: "DiskSnap",
    bat: Optional["BatterySnap"],
    swap_used: int,
    width: int,
) -> str:
    color = _level_color(v.level)
    if v.name == "CPU":
        # 堆叠：用户(青) + 系统(品红) + 空闲(暗)
        user = snap.cpu_user / 100
        sysv = snap.cpu_sys / 100
        return _stack_bar([(user, CYAN), (sysv, MAG)], width)
    if v.name == "内存" and snap.phys_total_b:
        # 堆叠：wired(红) + compressor(黄) + 其他已用(青) + 空闲(暗)
        total = snap.phys_total_b
        wired = snap.wired_b / total
        comp = snap.compressor_b / total
        other_used = max(0, (snap.phys_used_b - snap.wired_b - snap.compressor_b) / total)
        return _stack_bar([(wired, RED), (comp, YELLOW), (other_used, CYAN)], width)
    if v.name == "网络":
        ratio = (net.in_bps + net.out_bps) / (100 * 1024**2)
        return _bar(ratio, width, color)
    if v.name == "磁盘":
        ratio = disk.bps / (500 * 1024**2)
        return _bar(ratio, width, color)
    if v.name == "电池" and bat:
        # 电池图标风：[████░░] 满则绿，<20% 红，否则按状态
        pct = bat.pct / 100
        if bat.pct < 20:
            c = RED
        elif bat.on_battery:
            c = YELLOW
        else:
            c = GREEN
        return _bar(pct, width, c)
    return _bar(0, width, color)


def _proc_color(value: float, hi: float, mid: float) -> str:
    if value >= hi:
        return RED
    if value >= mid:
        return YELLOW
    return GREEN


def _verdict_ratio(
    v: Verdict,
    snap: TopSnap,
    net: "NetSnap",
    disk: "DiskSnap",
    bat: Optional["BatterySnap"],
) -> float:
    """每项映射到 0..1 用于画主条。"""
    if v.name == "CPU":
        return (100 - snap.cpu_idle) / 100
    if v.name == "内存":
        if not snap.phys_total_b:
            return 0
        return snap.phys_used_b / snap.phys_total_b
    if v.name == "网络":
        # 100 MB/s 满条
        total = (net.in_bps + net.out_bps) / (100 * 1024**2)
        return total
    if v.name == "磁盘":
        # 500 MB/s 满条
        return disk.bps / (500 * 1024**2)
    if v.name == "电池":
        return (bat.pct if bat else 0) / 100
    return 0


def _suggest(verdicts: List[Verdict]) -> List[str]:
    out: List[str] = []
    for v in verdicts:
        if v.level == "ok":
            continue
        if v.name == "CPU":
            top = v.detail.split("  ")[0] if v.detail else ""
            if top:
                out.append(f"CPU 主要在 {top.split()[0]}，看是否有失控的循环或可关掉的 tab")
        elif v.name == "内存":
            if "swap" in v.headline:
                out.append("已经在用 swap，机器很快会卡。考虑关掉占内存最多的应用")
            else:
                top = v.detail.split("  ")[0] if v.detail else ""
                if top:
                    out.append(f"内存吃紧，{top.split()[0]} 占大头")
        elif v.name == "磁盘":
            out.append("磁盘繁忙，可能是 Spotlight/Time Machine/虚拟机后台 IO；观察是否持续")
        elif v.name == "网络":
            out.append("有大流量在跑，确认是同步/上传任务而不是被占用")
        elif v.name == "电池":
            if v.level == "high":
                out.append(f"电量低 + 高负载，赶紧插电源")
            elif v.level == "warn":
                out.append(f"放电功率高，看 CPU 是否同时高（共因）")
    return out


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="loadx",
        description="一句话告诉你机器现在累在哪",
    )
    parser.add_argument("-w", "--watch", type=float, nargs="?", const=3.0,
                        help="持续刷新（秒，默认 3）")
    parser.add_argument("--no-net", action="store_true", help="跳过网络采样（更快）")
    parser.add_argument("--no-disk", action="store_true", help="跳过磁盘采样（更快）")
    args = parser.parse_args()

    history: Dict[str, List[float]] = {"cpu": [], "mem": [], "net": [], "disk": [], "bat": []}
    HISTORY_MAX = 60

    import io
    import threading
    from concurrent.futures import ThreadPoolExecutor

    # watch 模式：net/disk 在后台线程持续采样，主循环读最新缓存（懒加载）
    cache_lock = threading.Lock()
    cached_net: Dict[str, Optional[NetSnap]] = {"v": None}
    cached_disk: Dict[str, Optional[DiskSnap]] = {"v": None}
    stop_evt = threading.Event()

    def _bg_net() -> None:
        while not stop_evt.is_set():
            ns = sample_net(interval=1.0)
            with cache_lock:
                cached_net["v"] = ns

    def _bg_disk() -> None:
        while not stop_evt.is_set():
            ds = sample_disk()
            with cache_lock:
                cached_disk["v"] = ds

    def _capture(fn, *fa, **fk) -> str:
        sio = io.StringIO()
        old = sys.stdout
        sys.stdout = sio
        try:
            fn(*fa, **fk)
        finally:
            sys.stdout = old
        return sio.getvalue()

    def _draw_frame(in_watch: bool) -> None:
        if in_watch:
            with cache_lock:
                net = cached_net["v"] or NetSnap()
                disk = cached_disk["v"] or DiskSnap()
                net_ready = cached_net["v"] is not None
                disk_ready = cached_disk["v"] is not None
            top = sample_top()  # 主循环只等 top（~1.3s）
        else:
            with ThreadPoolExecutor(max_workers=3) as ex:
                f_top = ex.submit(sample_top)
                f_net = ex.submit(lambda: NetSnap()) if args.no_net else ex.submit(sample_net, 1.0)
                f_disk = ex.submit(lambda: DiskSnap()) if args.no_disk else ex.submit(sample_disk)
                top = f_top.result()
                net = f_net.result()
                disk = f_disk.result()
            net_ready = disk_ready = True

        hw = sample_hw()
        vm = sample_vm_stat()
        swap_used, swap_total = sample_swap()
        bat = sample_battery()

        verdicts = [
            assess_cpu(top, hw),
            assess_mem(top, vm, swap_used, swap_total),
            assess_net(net) if net_ready else Verdict("网络", "ok", f"{DIM}采样中…{RESET}", ""),
            assess_disk(disk) if disk_ready else Verdict("磁盘", "ok", f"{DIM}采样中…{RESET}", ""),
        ]
        bv = assess_battery(bat)
        if bv:
            verdicts.append(bv)

        history["cpu"].append((100 - top.cpu_idle) / 100)
        history["mem"].append(top.phys_used_b / top.phys_total_b if top.phys_total_b else 0)
        if net_ready:
            history["net"].append(min(1.0, (net.in_bps + net.out_bps) / (100 * 1024**2)))
        if disk_ready:
            history["disk"].append(min(1.0, disk.bps / (500 * 1024**2)))
        history["bat"].append((bat.pct if bat else 0) / 100)
        for k in history:
            if len(history[k]) > HISTORY_MAX:
                history[k] = history[k][-HISTORY_MAX:]

        body = _capture(render, verdicts, hw, top, swap_used, net, disk, bat,
                        history=history if in_watch else None)

        if in_watch:
            footer = (f"\n{DIM}↻ 每 {args.watch:g}s 刷新  ·  历史 "
                      f"{len(history['cpu'])}/{HISTORY_MAX}  ·  "
                      f"net {'✓' if net_ready else '…'}  disk {'✓' if disk_ready else '…'}"
                      f"  （Ctrl-C 退出）{RESET}\n")
            body += footer
            # 防闪：cursor home → 每行末 EL → 末尾 ED
            sys.stdout.write("\x1b[H")
            for line in body.splitlines():
                sys.stdout.write(line + "\x1b[K\n")
            sys.stdout.write("\x1b[J")
            sys.stdout.flush()
        else:
            sys.stdout.write(body)
            sys.stdout.flush()

    if args.watch:
        if not args.no_net:
            threading.Thread(target=_bg_net, daemon=True).start()
        if not args.no_disk:
            threading.Thread(target=_bg_disk, daemon=True).start()
        sys.stdout.write("\x1b[2J\x1b[H")  # 首次进入清一次屏
        sys.stdout.flush()
        try:
            while True:
                _draw_frame(in_watch=True)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            stop_evt.set()
            sys.stdout.write("\n")
            return 0
    else:
        _draw_frame(in_watch=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
