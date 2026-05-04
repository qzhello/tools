#!/usr/bin/env python3
"""tracex - 可视化路由追踪（mtr 风格）。

循环跑 traceroute，按跳累计统计：丢包率、最近/平均/p95 延迟、sparkline。
看哪一跳在抖动 / 丢包，比 traceroute 单次结果信息量大得多。
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections import deque
from typing import Deque, Dict, List, Optional

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("TRACEX_FORCE_COLOR") or sys.stdout.isatty())
)


def _c(code: str) -> str:
    return code if _USE_COLOR else ""


DIM    = _c("\x1b[2m")
BOLD   = _c("\x1b[1m")
CYAN   = _c("\x1b[36m")
GREEN  = _c("\x1b[32m")
YELLOW = _c("\x1b[33m")
RED    = _c("\x1b[31m")
GRAY   = _c("\x1b[90m")
RESET  = _c("\x1b[0m")

HIDE_CURSOR = "\x1b[?25l" if _USE_COLOR else ""
SHOW_CURSOR = "\x1b[?25h" if _USE_COLOR else ""

SPARK = "▁▂▃▄▅▆▇█"

GOOD_MS = 50
WARN_MS = 150


def latency_color(ms: float) -> str:
    if ms < GOOD_MS:
        return GREEN
    if ms < WARN_MS:
        return YELLOW
    return RED


def loss_color(pct: float) -> str:
    if pct == 0:
        return GREEN
    if pct < 20:
        return YELLOW
    return RED


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def render_sparkline(samples: Deque[Optional[float]]) -> str:
    if not samples:
        return ""
    valid = [s for s in samples if s is not None]
    hi = max([WARN_MS / 3, max(valid) if valid else 0]) * 1.2
    hi = max(hi, 1.0)
    out = []
    for s in samples:
        if s is None:
            out.append(f"{GRAY}✗{RESET}")
            continue
        n = min(s / hi, 1.0)
        idx = max(0, min(len(SPARK) - 1, int(n * (len(SPARK) - 1))))
        out.append(f"{latency_color(s)}{SPARK[idx]}{RESET}")
    return "".join(out)


class HopStat:
    def __init__(self, window: int):
        self.ip: Optional[str] = None
        self.ip_alts: Dict[str, int] = {}
        self.sent = 0
        self.recv = 0
        self.latencies: List[float] = []
        self.recent: Deque[Optional[float]] = deque(maxlen=window)

    def record(self, ip: Optional[str], rtt: Optional[float]) -> None:
        self.sent += 1
        if ip:
            self.ip_alts[ip] = self.ip_alts.get(ip, 0) + 1
            # 多 IP 时取出现次数最多的
            self.ip = max(self.ip_alts.items(), key=lambda kv: kv[1])[0]
        if rtt is not None:
            self.recv += 1
            self.latencies.append(rtt)
            self.recent.append(rtt)
        else:
            self.recent.append(None)

    @property
    def loss_pct(self) -> float:
        return (self.sent - self.recv) * 100 / self.sent if self.sent else 0.0


HOP_LINE_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
RTT_RE      = re.compile(r"([\d.]+)\s+ms")
IP_RE       = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]+:[0-9a-fA-F:]*)")


def trace_once(host: str, max_hops: int, wait: int, use_icmp: bool) -> Dict[int, dict]:
    """跑一次 traceroute，返回 {hop_n: {"ip": str|None, "rtt": float|None}}."""
    cmd = ["traceroute", "-n", "-q", "1", "-w", str(wait), "-m", str(max_hops)]
    if use_icmp:
        cmd.append("-I")
    cmd.append(host)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        sys.exit("✗ 找不到 traceroute")

    hops: Dict[int, dict] = {}
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line or line.startswith("traceroute"):
                continue
            m = HOP_LINE_RE.match(line)
            if not m:
                continue
            hop_n = int(m.group(1))
            rest = m.group(2)
            ip_m = IP_RE.search(rest)
            ip = ip_m.group(1) if ip_m else None
            rtt_m = RTT_RE.search(rest)
            rtt = float(rtt_m.group(1)) if rtt_m else None
            hops[hop_n] = {"ip": ip, "rtt": rtt}
    except (KeyboardInterrupt, BrokenPipeError):
        proc.terminate()
    proc.wait()
    return hops


def disp_width(s: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - disp_width(s))


def render_table(hops: Dict[int, HopStat], max_hop: int, window: int,
                 host: str, target_ip: str, round_n: int) -> List[str]:
    out: List[str] = []
    out.append(
        f"{BOLD}tracex{RESET} {host}"
        + (f"  {DIM}({target_ip}){RESET}" if target_ip and target_ip != host else "")
        + f"  {DIM}round {round_n}{RESET}"
    )
    out.append("")

    cols = ["跳", "IP", "丢包", "最后", "平均", "p95", "最近"]
    rows = []
    for n in range(1, max_hop + 1):
        stat = hops.get(n)
        if not stat or stat.sent == 0:
            rows.append([str(n), "*", "—", "—", "—", "—", ""])
            continue
        ip_disp = stat.ip or "*"
        loss = f"{stat.sent - stat.recv}/{stat.sent} {stat.loss_pct:.0f}%"
        if stat.latencies:
            last = f"{stat.latencies[-1]:.1f}" if stat.recent and stat.recent[-1] is not None else "—"
            avg = f"{sum(stat.latencies) / len(stat.latencies):.1f}"
            p95 = f"{percentile(stat.latencies, 95):.1f}"
        else:
            last = avg = p95 = "—"
        spark = render_sparkline(stat.recent) if stat.recent else ""
        rows.append([str(n), ip_disp, loss, last, avg, p95, spark])

    widths = []
    for i, c in enumerate(cols):
        if c == "最近":
            widths.append(disp_width(c))
            continue
        w = max(disp_width(c), max((disp_width(r[i]) for r in rows), default=0))
        widths.append(w)

    header = "  ".join(f"{CYAN}{pad(c, widths[i])}{RESET}" for i, c in enumerate(cols))
    out.append(header)
    out.append(f"{DIM}{'  '.join('─' * w for w in widths)}{RESET}")

    for n, r in zip(range(1, max_hop + 1), rows):
        stat = hops.get(n)
        # 跳号
        c0 = f"{DIM}{pad(r[0], widths[0])}{RESET}"
        # IP
        if r[1] == "*":
            c1 = f"{GRAY}{pad(r[1], widths[1])}{RESET}"
        elif stat and stat.ip == target_ip:
            c1 = f"{BOLD}{pad(r[1], widths[1])}{RESET}"
        else:
            c1 = pad(r[1], widths[1])
        # loss
        if stat and stat.sent > 0:
            c2 = f"{loss_color(stat.loss_pct)}{pad(r[2], widths[2])}{RESET}"
        else:
            c2 = f"{GRAY}{pad(r[2], widths[2])}{RESET}"
        # last/avg/p95
        if r[3] != "—":
            c3 = f"{latency_color(stat.latencies[-1])}{pad(r[3], widths[3])}{RESET}"
            avg_v = sum(stat.latencies) / len(stat.latencies)
            c4 = f"{latency_color(avg_v)}{pad(r[4], widths[4])}{RESET}"
            c5 = f"{latency_color(percentile(stat.latencies, 95))}{pad(r[5], widths[5])}{RESET}"
        else:
            c3 = f"{GRAY}{pad(r[3], widths[3])}{RESET}"
            c4 = f"{GRAY}{pad(r[4], widths[4])}{RESET}"
            c5 = f"{GRAY}{pad(r[5], widths[5])}{RESET}"
        # spark（已带颜色，不补宽）
        c6 = r[6]
        out.append(f"  {c0}  {c1}  {c2}  {c3}  {c4}  {c5}  {c6}")

    return out


class LiveRenderer:
    def __init__(self) -> None:
        self.line_count = 0

    def draw(self, lines: List[str]) -> None:
        out = sys.stdout
        if self.line_count:
            out.write(f"\x1b[{self.line_count}A")
        for line in lines:
            out.write("\x1b[2K")
            out.write(line)
            out.write("\n")
        self.line_count = len(lines)
        out.flush()


def resolve(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except (socket.gaierror, OSError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tracex",
        description="可视化路由追踪（mtr 风格，基于 traceroute）",
    )
    p.add_argument("host", help="目标主机或 IP")
    p.add_argument("-m", "--max-hops", type=int, default=30,
                   help="最大跳数（默认 30）")
    p.add_argument("-w", "--wait", type=int, default=1,
                   help="单跳等待秒数（默认 1）")
    p.add_argument("-c", "--count", type=int, default=0,
                   help="跑 N 轮后退出（默认 0 = 无限）")
    p.add_argument("-W", "--window", type=int, default=15,
                   help="sparkline 窗口（默认 15）")
    p.add_argument("--icmp", action="store_true",
                   help="使用 ICMP 探测（穿透性更好，需 sudo）")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    if args.window < 3:
        print("✗ --window 至少 3", file=sys.stderr)
        return 1

    target_ip = resolve(args.host)

    print(f"{BOLD}tracex{RESET} {args.host}"
          + (f"  {DIM}({target_ip}){RESET}" if target_ip and target_ip != args.host else "")
          + f"  {DIM}(Ctrl-C 退出){RESET}")
    print()
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    hops: Dict[int, HopStat] = {}
    max_hop_seen = 0
    renderer = LiveRenderer()
    interrupted = {"flag": False}

    def on_sigint(_sig, _frame):
        interrupted["flag"] = True

    signal.signal(signal.SIGINT, on_sigint)

    round_n = 0
    try:
        while not interrupted["flag"]:
            round_n += 1
            try:
                result = trace_once(args.host, args.max_hops, args.wait, args.icmp)
            except KeyboardInterrupt:
                break
            if not result and round_n == 1:
                print(f"{RED}✗ traceroute 没有返回任何跳，检查网络或目标{RESET}", file=sys.stderr)
                return 1
            for hop_n, info in result.items():
                if hop_n not in hops:
                    hops[hop_n] = HopStat(window=args.window)
                hops[hop_n].record(info["ip"], info["rtt"])
            if result:
                max_hop_seen = max(max_hop_seen, max(result.keys()))
            renderer.draw(render_table(
                hops, max_hop_seen, args.window, args.host, target_ip, round_n,
            ))
            if args.count and round_n >= args.count:
                break
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(0)
