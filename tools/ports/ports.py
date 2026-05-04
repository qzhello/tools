#!/usr/bin/env python3
"""ports - 列出本机监听端口 + 进程 + 用户。

包装 lsof，按 (proto, port, pid) 去重，识别常见服务，
支持按端口号或进程名过滤，支持 -k 杀进程（带二次确认）。
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import re
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("PORTS_FORCE_COLOR") or sys.stdout.isatty())
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

WELL_KNOWN: Dict[int, str] = {
    22: "ssh", 25: "smtp", 53: "dns", 80: "http", 88: "kerberos",
    110: "pop3", 143: "imap", 389: "ldap", 443: "https", 445: "smb",
    465: "smtps", 587: "submission", 631: "ipp", 636: "ldaps",
    993: "imaps", 995: "pop3s",
    1433: "mssql", 1521: "oracle", 1883: "mqtt",
    2049: "nfs", 2181: "zookeeper",
    3000: "node-dev", 3001: "node-dev", 3306: "mysql", 3307: "mysql",
    3389: "rdp", 3478: "stun",
    4000: "dev", 4200: "ng-dev", 4317: "otlp", 4318: "otlp-http",
    5000: "flask/upnp", 5060: "sip", 5173: "vite", 5222: "xmpp",
    5353: "mdns", 5432: "postgres", 5433: "postgres", 5672: "amqp",
    5900: "vnc", 5984: "couch",
    6379: "redis", 6380: "redis", 6443: "k8s-api", 6660: "irc",
    7000: "cassandra", 7474: "neo4j", 7687: "neo4j",
    8000: "dev", 8008: "http-alt", 8080: "http-alt", 8081: "http-alt",
    8443: "https-alt", 8500: "consul", 8888: "jupyter",
    9000: "php-fpm", 9090: "prometheus", 9092: "kafka", 9200: "elastic",
    9300: "elastic", 9418: "git",
    11211: "memcached", 15672: "rabbitmq-mgmt",
    19132: "minecraft-be", 25565: "minecraft",
    27017: "mongo", 27018: "mongo",
    50051: "grpc",
}


# lsof name 字段匹配：
#   *:22  /  127.0.0.1:8080  /  [::1]:5432  /  [::]:443
ADDR_RE = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[0-9.]+|\*):(\d+)$")


def run_lsof(args: List[str]) -> str:
    try:
        proc = subprocess.run(
            ["lsof", *args, "-P", "-n"],
            capture_output=True, check=False,
        )
    except FileNotFoundError:
        sys.exit("✗ 找不到 lsof")
    # lsof 偶尔会有非 UTF-8 字节（异常进程名），用 replace 兜底
    return proc.stdout.decode("utf-8", errors="replace")


def collect() -> List[Dict]:
    seen: Dict[Tuple[str, int, int], Dict] = {}
    sources = [
        ("TCP", ["-iTCP", "-sTCP:LISTEN"]),
        ("UDP", ["-iUDP"]),
    ]
    for proto, args in sources:
        out = run_lsof(args)
        lines = out.splitlines()
        if not lines:
            continue
        for line in lines[1:]:  # 跳过表头
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            cmd, pid, user, fd, typ, dev, size, node, name = parts
            # 过滤已建立的连接（含 "->" 表示 src->dst）
            if "->" in name:
                continue
            addr_part = name.split(" ", 1)[0]
            m = ADDR_RE.match(addr_part)
            if not m:
                continue
            addr, port_s = m.group(1), m.group(2)
            try:
                port = int(port_s)
            except ValueError:
                continue
            try:
                pid_n = int(pid)
            except ValueError:
                continue
            # 归一化监听地址
            if addr in ("*", "0.0.0.0", "[::]"):
                addr_norm = "*"
            else:
                addr_norm = addr.strip("[]")

            key = (proto, port, pid_n)
            if key in seen:
                # 同一进程同一端口（IPv4 + IPv6）合并：通配优先
                if seen[key]["addr"] != "*" and addr_norm == "*":
                    seen[key]["addr"] = "*"
                continue
            seen[key] = {
                "proto": proto,
                "port": port,
                "addr": addr_norm,
                "cmd": cmd,
                "pid": pid_n,
                "user": user,
                "service": WELL_KNOWN.get(port, ""),
            }
    return sorted(seen.values(), key=lambda e: (e["port"], e["proto"]))


def matches_filter(entry: Dict, q: Optional[str]) -> bool:
    if not q:
        return True
    if q.isdigit():
        return entry["port"] == int(q)
    return q.lower() in entry["cmd"].lower() or q.lower() in entry["service"].lower()


def disp_width(s: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - disp_width(s))


def proto_color(proto: str) -> str:
    return CYAN if proto == "TCP" else MAG


def addr_color(addr: str) -> str:
    if addr == "*":
        return YELLOW
    if addr.startswith("127.") or addr in ("::1",):
        return GREEN
    return RESET


def render_table(entries: List[Dict]) -> None:
    if not entries:
        print(f"{DIM}（没有监听端口）{RESET}")
        return

    cols = ["端口", "协议", "监听地址", "服务", "进程", "PID", "用户"]
    rows = []
    for e in entries:
        rows.append([
            str(e["port"]),
            e["proto"],
            e["addr"],
            e["service"] or "-",
            e["cmd"],
            str(e["pid"]),
            e["user"],
        ])
    widths = [max(disp_width(c), max((disp_width(r[i]) for r in rows), default=0))
              for i, c in enumerate(cols)]

    header = "  ".join(f"{CYAN}{pad(c, widths[i])}{RESET}" for i, c in enumerate(cols))
    print(header)
    print(f"{DIM}{'  '.join('─' * w for w in widths)}{RESET}")

    for e, r in zip(entries, rows):
        port_col = f"{BOLD}{pad(r[0], widths[0])}{RESET}"
        proto_col = f"{proto_color(e['proto'])}{pad(r[1], widths[1])}{RESET}"
        addr_col = f"{addr_color(e['addr'])}{pad(r[2], widths[2])}{RESET}"
        svc = r[3]
        svc_col = f"{GREEN}{pad(svc, widths[3])}{RESET}" if e["service"] else f"{DIM}{pad(svc, widths[3])}{RESET}"
        cmd_col = pad(r[4], widths[4])
        pid_col = f"{DIM}{pad(r[5], widths[5])}{RESET}"
        user_col = pad(r[6], widths[6])
        print(f"{port_col}  {proto_col}  {addr_col}  {svc_col}  {cmd_col}  {pid_col}  {user_col}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 存在但无权限发信号
        return True


def cmd_kill(entries: List[Dict], assume_yes: bool) -> int:
    if not entries:
        print("没有匹配的监听端口")
        return 1
    print(f"将 {RED}杀掉{RESET} 以下 {len(entries)} 个进程：")
    for e in entries:
        print(f"  {DIM}{e['proto']:>3}{RESET} {BOLD}{e['port']}{RESET}  "
              f"PID {e['pid']:<6} {e['cmd']}  {DIM}({e['user']}){RESET}")
    if not assume_yes:
        try:
            ans = input(f"\n确认？{DIM}[y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 0
        if ans not in ("y", "yes"):
            print("已取消")
            return 0

    pids = sorted({e["pid"] for e in entries})
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

    print(f"\n{YELLOW}{len(still)} 个进程未响应 SIGTERM{RESET}")
    if not assume_yes:
        try:
            ans = input(f"用 SIGKILL 强杀？{DIM}[y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 0
        if ans not in ("y", "yes"):
            print("已取消")
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
        prog="ports",
        description="列出本机监听端口（TCP+UDP），支持过滤与杀进程",
    )
    p.add_argument("filter", nargs="?", default=None,
                   help="按端口号（数字）或进程名/服务名（字符串）过滤")
    p.add_argument("-k", "--kill", action="store_true",
                   help="杀掉匹配的进程（带二次确认）")
    p.add_argument("-y", "--yes", action="store_true",
                   help="--kill 时跳过所有确认（危险）")
    p.add_argument("-j", "--json", action="store_true",
                   help="JSON 输出（脚本用）")
    p.add_argument("--tcp", action="store_true", help="仅 TCP")
    p.add_argument("--udp", action="store_true", help="仅 UDP")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    entries = collect()
    if args.tcp and not args.udp:
        entries = [e for e in entries if e["proto"] == "TCP"]
    elif args.udp and not args.tcp:
        entries = [e for e in entries if e["proto"] == "UDP"]
    entries = [e for e in entries if matches_filter(e, args.filter)]

    if args.kill:
        if not args.filter:
            print("✗ --kill 需要指定过滤条件（端口号或进程名）", file=sys.stderr)
            return 1
        return cmd_kill(entries, assume_yes=args.yes)

    if args.json:
        print(jsonlib.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    render_table(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
