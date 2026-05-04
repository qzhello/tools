#!/usr/bin/env python3
"""pingx - 实时可视化 ping。

包装系统 ping，解析输出，绘制：
  - 目标 / 已发送 / 丢包率
  - 当前延迟 + 滚动 sparkline
  - min / avg / p95 / max

Ctrl-C 退出后打印汇总。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from typing import Deque, List, Optional

# ANSI 配色
_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("PINGX_FORCE_COLOR") or sys.stdout.isatty())
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

REPLY_RE   = re.compile(r"icmp_seq=(\d+).*?time=([\d.]+)\s*ms")
TIMEOUT_RE = re.compile(r"[Rr]equest timeout for icmp_seq\s+(\d+)")
HEADER_RE  = re.compile(r"^PING\s+(\S+)\s+\(([^)]+)\)")

# 颜色阈值（毫秒）
GOOD_MS = 50
WARN_MS = 150


def latency_color(ms: float) -> str:
    if ms < GOOD_MS:
        return GREEN
    if ms < WARN_MS:
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
    """从 0 到 max(50, p95×1.2) 做映射，None 显示为灰色 ✗。"""
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


def fmt_ms(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}"


class Stats:
    def __init__(self, window: int):
        self.target = ""
        self.ip = ""
        self.sent = 0
        self.recv = 0
        self.latencies: List[float] = []
        self.recent: Deque[Optional[float]] = deque(maxlen=window)
        self.start = time.monotonic()

    def add_reply(self, ms: float) -> None:
        self.sent += 1
        self.recv += 1
        self.latencies.append(ms)
        self.recent.append(ms)

    def add_timeout(self) -> None:
        self.sent += 1
        self.recent.append(None)

    @property
    def lost(self) -> int:
        return self.sent - self.recv

    @property
    def loss_pct(self) -> float:
        return (self.lost * 100 / self.sent) if self.sent else 0.0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start


def render_lines(stats: Stats, window: int) -> List[str]:
    target = stats.target or "?"
    if stats.ip and stats.ip != target:
        target = f"{target} {DIM}→{RESET} {stats.ip}"

    cur = stats.latencies[-1] if stats.recent and stats.recent[-1] is not None else None
    if cur is not None:
        cur_str = f"{latency_color(cur)}{fmt_ms(cur)} ms{RESET}"
    elif stats.recent and stats.recent[-1] is None:
        cur_str = f"{RED}超时{RESET}"
    else:
        cur_str = f"{GRAY}—{RESET}"

    if stats.loss_pct == 0:
        loss_color = GREEN
    elif stats.loss_pct < 5:
        loss_color = YELLOW
    else:
        loss_color = RED
    loss_str = f"{loss_color}{stats.lost} ({stats.loss_pct:.1f}%){RESET}"

    if stats.latencies:
        mn = min(stats.latencies)
        mx = max(stats.latencies)
        avg = sum(stats.latencies) / len(stats.latencies)
        p95 = percentile(stats.latencies, 95)
        lat_str = (
            f"min {GREEN}{fmt_ms(mn)}{RESET}  "
            f"avg {YELLOW}{fmt_ms(avg)}{RESET}  "
            f"p95 {YELLOW}{fmt_ms(p95)}{RESET}  "
            f"max {RED}{fmt_ms(mx)}{RESET} ms"
        )
    else:
        lat_str = f"{GRAY}暂无数据{RESET}"

    spark = render_sparkline(stats.recent)
    spark_label = f"{DIM}最近 {len(stats.recent)}/{window}{RESET}"

    return [
        f"  {CYAN}目标{RESET}    {target}",
        f"  {CYAN}已发送{RESET}  {stats.sent}    {CYAN}丢包{RESET}  {loss_str}    {DIM}用时 {stats.elapsed:.0f}s{RESET}",
        f"  {CYAN}当前{RESET}    {cur_str}",
        f"  {CYAN}最近{RESET}    {spark}  {spark_label}",
        f"  {CYAN}延迟{RESET}    {lat_str}",
    ]


class LiveRenderer:
    def __init__(self) -> None:
        self.line_count = 0

    def draw(self, lines: List[str]) -> None:
        out = sys.stdout
        if self.line_count:
            out.write(f"\x1b[{self.line_count}A")
        for line in lines:
            out.write("\x1b[2K")  # 清行
            out.write(line)
            out.write("\n")
        self.line_count = len(lines)
        out.flush()


def print_summary(stats: Stats) -> None:
    print()
    print(f"{BOLD}── 汇总 ──{RESET}")
    target = stats.target or "?"
    if stats.ip and stats.ip != target:
        target = f"{target} → {stats.ip}"
    print(f"  目标      {target}")
    print(f"  发送 / 接收 / 丢失   "
          f"{stats.sent} / {GREEN}{stats.recv}{RESET} / "
          f"{RED if stats.lost else GREEN}{stats.lost}{RESET} "
          f"({stats.loss_pct:.1f}% 丢包)")
    if stats.latencies:
        mn = min(stats.latencies)
        mx = max(stats.latencies)
        avg = sum(stats.latencies) / len(stats.latencies)
        p50 = percentile(stats.latencies, 50)
        p95 = percentile(stats.latencies, 95)
        p99 = percentile(stats.latencies, 99)
        print(
            f"  延迟      min {fmt_ms(mn)}  avg {fmt_ms(avg)}  "
            f"max {fmt_ms(mx)} ms"
        )
        print(
            f"  分位      p50 {fmt_ms(p50)}  p95 {fmt_ms(p95)}  "
            f"p99 {fmt_ms(p99)} ms"
        )
    print(f"  用时      {stats.elapsed:.1f}s")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pingx",
        description="实时可视化 ping（sparkline + 统计）",
    )
    p.add_argument("host", help="目标主机或 IP")
    p.add_argument("-i", "--interval", type=float, default=1.0,
                   help="发送间隔（秒，默认 1.0；< 1 在 macOS 需要 sudo）")
    p.add_argument("-c", "--count", type=int, default=0,
                   help="发送 N 个包后退出（默认 0 = 无限）")
    p.add_argument("-w", "--window", type=int, default=60,
                   help="sparkline 窗口大小（默认 60）")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    if args.window < 5:
        print("✗ --window 至少 5", file=sys.stderr)
        return 1

    cmd = ["ping", "-i", str(args.interval)]
    if args.count > 0:
        cmd += ["-c", str(args.count)]
    cmd.append(args.host)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print("✗ 找不到 ping 命令", file=sys.stderr)
        return 1

    stats = Stats(window=args.window)
    renderer = LiveRenderer()

    print(f"{BOLD}pingx{RESET} {args.host}  {DIM}(Ctrl-C 退出){RESET}")
    print()
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    # Ctrl-C：先尝试温柔停止 ping
    interrupted = {"flag": False}

    def on_sigint(_sig, _frame):
        if interrupted["flag"]:
            return
        interrupted["flag"] = True
        try:
            proc.terminate()
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGINT, on_sigint)

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            m = HEADER_RE.match(line)
            if m:
                stats.target = m.group(1)
                stats.ip = m.group(2)
                renderer.draw(render_lines(stats, args.window))
                continue

            m = REPLY_RE.search(line)
            if m:
                ms = float(m.group(2))
                stats.add_reply(ms)
                renderer.draw(render_lines(stats, args.window))
                continue

            m = TIMEOUT_RE.search(line)
            if m:
                stats.add_timeout()
                renderer.draw(render_lines(stats, args.window))
                continue

            # ping 自身的错误：cannot resolve / sendto / etc.
            if line.startswith("ping:") or "cannot resolve" in line.lower():
                # 把错误显示到独立行，不影响 live 块
                sys.stdout.write("\x1b[2K")
                print(f"{RED}{line}{RESET}")
                renderer.line_count = 0  # 强制重画
                continue

            # 汇总行（如 "--- baidu.com ping statistics ---"）等忽略
    except KeyboardInterrupt:
        on_sigint(None, None)
    finally:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        print_summary(stats)

    if stats.sent > 0 and stats.recv == 0:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(0)
