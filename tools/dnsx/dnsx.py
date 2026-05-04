#!/usr/bin/env python3
"""dnsx - 多 resolver DNS 对比查询。

并行查询多个 DNS 服务器（系统、Google、Cloudflare、114、阿里），
对每种记录类型展示返回值，结果不一致时高亮。
排查 CDN 路由 / DNS 污染 / 解析未生效时很有用。
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("DNSX_FORCE_COLOR") or sys.stdout.isatty())
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

# (显示名, server IP 或 None=系统)
DEFAULT_RESOLVERS: List[Tuple[str, Optional[str]]] = [
    ("系统",        None),
    ("Google",      "8.8.8.8"),
    ("Cloudflare",  "1.1.1.1"),
    ("114DNS",      "114.114.114.114"),
    ("阿里",        "223.5.5.5"),
]

DEFAULT_TYPES = ["A", "AAAA", "CNAME", "NS", "MX", "TXT"]
ALL_TYPES = ["A", "AAAA", "CNAME", "NS", "MX", "TXT", "SOA", "PTR", "SRV", "CAA"]


def dig_query(host: str, rtype: str, server: Optional[str], timeout: int) -> Optional[List[str]]:
    cmd = ["dig", "+short", f"+time={timeout}", "+tries=1"]
    if server:
        cmd.append(f"@{server}")
    cmd += [host, rtype]
    try:
        result = subprocess.run(
            cmd, capture_output=True, check=False, timeout=timeout + 2,
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        sys.exit("✗ 找不到 dig")
    if result.returncode != 0:
        return None
    out = result.stdout.decode("utf-8", errors="replace")
    lines = []
    for raw in out.splitlines():
        s = raw.strip()
        if not s or s.startswith(";"):
            continue
        lines.append(s)
    return lines


def query_all(host: str, types: List[str],
              resolvers: List[Tuple[str, Optional[str]]],
              timeout: int) -> Dict[str, Dict[str, Optional[List[str]]]]:
    """returns {rtype: {resolver_name: [values] or None}}."""
    tasks = []
    for rtype in types:
        for name, server in resolvers:
            tasks.append((rtype, name, server))

    out: Dict[str, Dict[str, Optional[List[str]]]] = {t: {} for t in types}
    with ThreadPoolExecutor(max_workers=min(16, len(tasks) or 1)) as ex:
        futures = {
            ex.submit(dig_query, host, t, server, timeout): (t, name)
            for t, name, server in tasks
        }
        for fut in futures:
            t, name = futures[fut]
            try:
                out[t][name] = fut.result()
            except Exception:
                out[t][name] = None
    return out


def normalize_value(v: str) -> str:
    """记录值归一化：去末尾点，A/AAAA 多值排序时分开比较即可。"""
    return v.rstrip(".") if v else v


def value_set(values: Optional[List[str]]) -> Optional[frozenset]:
    if values is None:
        return None
    return frozenset(normalize_value(v) for v in values)


def render_section(rtype: str, per_resolver: Dict[str, Optional[List[str]]],
                   resolver_order: List[str]) -> None:
    # 收集所有非 None 的值集合，判断一致性
    sets = [value_set(per_resolver[r]) for r in resolver_order]
    non_none = [s for s in sets if s is not None]
    timeouts = [r for r, s in zip(resolver_order, sets) if s is None]
    no_record = [r for r, s in zip(resolver_order, sets) if s is not None and len(s) == 0]
    has_data = [r for r, s in zip(resolver_order, sets) if s and len(s) > 0]

    # 标题
    if not has_data:
        if timeouts and not no_record:
            status = f"{RED}✗ 全部超时{RESET}"
        elif no_record:
            status = f"{DIM}（无记录）{RESET}"
        else:
            status = f"{DIM}（无数据）{RESET}"
        print(f"{BOLD}{rtype:<6}{RESET}  {status}")
        return

    # 是否一致：所有有数据的 resolver 集合相同（忽略超时）
    data_sets = [s for s in non_none if len(s) > 0]
    consistent = len(set(data_sets)) <= 1 if data_sets else True

    if consistent and not timeouts and not no_record:
        status = f"{GREEN}✓ 一致{RESET}"
    elif consistent:
        notes = []
        if timeouts:
            notes.append(f"{RED}{len(timeouts)} 超时{RESET}")
        if no_record:
            notes.append(f"{DIM}{len(no_record)} 无记录{RESET}")
        status = f"{GREEN}✓ 一致{RESET}  ({'，'.join(notes)})"
    else:
        status = f"{YELLOW}⚠ 不一致{RESET}"

    print(f"{BOLD}{rtype:<6}{RESET}  {status}")

    # 列出每个独特值，标记哪些 resolver 返回了它
    # 按出现频率排序
    from collections import Counter
    value_to_resolvers: Dict[str, List[str]] = {}
    for r in resolver_order:
        s = per_resolver[r]
        if not s:
            continue
        for v in s:
            nv = normalize_value(v)
            value_to_resolvers.setdefault(nv, []).append(r)

    if value_to_resolvers:
        # 排序：返回它的 resolver 数量降序，再按值字典序
        sorted_vals = sorted(value_to_resolvers.items(),
                             key=lambda kv: (-len(kv[1]), kv[0]))
        all_resolver_count = len([s for s in non_none if len(s) > 0])
        for val, who in sorted_vals:
            if len(who) == all_resolver_count and consistent:
                tag = f"{DIM}[全部]{RESET}"
            else:
                tag = f"{DIM}[{', '.join(who)}]{RESET}"
            val_color = GREEN if rtype in ("A", "AAAA") else RESET
            print(f"        {val_color}{val}{RESET}  {tag}")

    if timeouts:
        print(f"        {RED}超时{RESET}: {DIM}{', '.join(timeouts)}{RESET}")
    if no_record and has_data:
        print(f"        {DIM}无记录: {', '.join(no_record)}{RESET}")
    print()


def render(host: str, results: Dict[str, Dict[str, Optional[List[str]]]],
           types: List[str], resolver_order: List[str]) -> None:
    print(f"{BOLD}dnsx{RESET} {host}  {DIM}via {len(resolver_order)} resolvers{RESET}")
    print()
    for t in types:
        render_section(t, results[t], resolver_order)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dnsx",
        description="多 DNS resolver 并行查询，对比并高亮差异",
    )
    p.add_argument("host", help="域名（或 IP，做反查时指定 -t PTR）")
    p.add_argument("-t", "--types",
                   help=f"逗号分隔的记录类型（默认: {','.join(DEFAULT_TYPES)}）")
    p.add_argument("--all-types", action="store_true",
                   help=f"查询所有支持类型: {','.join(ALL_TYPES)}")
    p.add_argument("-r", "--resolver", action="append",
                   help="额外的 resolver IP（可重复，如 -r 9.9.9.9 -r 8.8.4.4）")
    p.add_argument("--only", action="append",
                   help="仅使用指定 resolver（按显示名匹配，可重复）")
    p.add_argument("--timeout", type=int, default=3, help="单次查询超时秒数（默认 3）")
    p.add_argument("-j", "--json", action="store_true", help="JSON 输出")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    if args.all_types:
        types = ALL_TYPES
    elif args.types:
        types = [t.strip().upper() for t in args.types.split(",") if t.strip()]
    else:
        types = DEFAULT_TYPES

    resolvers = list(DEFAULT_RESOLVERS)
    if args.resolver:
        for ip in args.resolver:
            resolvers.append((ip, ip))
    if args.only:
        wanted = set()
        for raw in args.only:
            for part in raw.split(","):
                part = part.strip().lower()
                if part:
                    wanted.add(part)
        resolvers = [(n, s) for (n, s) in resolvers if n.lower() in wanted]
        if not resolvers:
            print(f"✗ --only 没有匹配到任何 resolver", file=sys.stderr)
            return 1

    results = query_all(args.host, types, resolvers, timeout=args.timeout)

    resolver_order = [n for n, _ in resolvers]

    if args.json:
        out = {
            "host": args.host,
            "resolvers": [{"name": n, "server": s} for n, s in resolvers],
            "records": {t: {n: results[t][n] for n in resolver_order} for t in types},
        }
        print(jsonlib.dumps(out, ensure_ascii=False, indent=2))
        return 0

    render(args.host, results, types, resolver_order)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
