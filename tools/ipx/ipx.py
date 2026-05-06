#!/usr/bin/env python3
"""ipx - 公网 IP + ISP + 地理位置 + 本机各网卡 IP。

并行查询多个公网 IP 服务，结果不一致时高亮（可能走了不同出口或被劫持）。
然后列出本机活动网卡的 v4/v6、默认网关、DNS。
"""

from __future__ import annotations

import argparse
import ipaddress
import json as jsonlib
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("IPX_FORCE_COLOR") or sys.stdout.isatty())
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


# (显示名, URL, 解析函数名)
# 解析函数返回 dict: ip / country / region / city / org / asn
@dataclass(frozen=True)
class Source:
    name: str
    url: str
    parser: str  # "ipinfo" | "ipapi" | "ifconfig" | "plain"
    family: str  # "v4" | "v6"


SOURCES: List[Source] = [
    Source("ipinfo.io",    "https://ipinfo.io/json",        "ipinfo",   "v4"),
    Source("ifconfig.co",  "https://ifconfig.co/json",      "ifconfig", "v4"),
    Source("ipapi.co",     "https://ipapi.co/json/",        "ipapi",    "v4"),
    Source("ipify",        "https://api.ipify.org",         "plain",    "v4"),
    Source("ipify6",       "https://api6.ipify.org",        "plain",    "v6"),
]


@dataclass
class IpResult:
    source: str
    ok: bool
    ip: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    org: Optional[str] = None
    asn: Optional[str] = None
    error: Optional[str] = None
    family: str = "v4"


def _http_get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ipx/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted hosts)
        data = resp.read()
        return data.decode("utf-8", errors="replace").strip()


def _parse_ipinfo(raw: str) -> Dict[str, Optional[str]]:
    j = jsonlib.loads(raw)
    return {
        "ip":      j.get("ip"),
        "country": j.get("country"),
        "region":  j.get("region"),
        "city":    j.get("city"),
        "org":     j.get("org"),
        "asn":     None,  # 包含在 org 字段里
    }


def _parse_ifconfigco(raw: str) -> Dict[str, Optional[str]]:
    j = jsonlib.loads(raw)
    return {
        "ip":      j.get("ip"),
        "country": j.get("country_iso") or j.get("country"),
        "region":  j.get("region_name"),
        "city":    j.get("city"),
        "org":     j.get("asn_org"),
        "asn":     j.get("asn"),
    }


def _parse_ipapi(raw: str) -> Dict[str, Optional[str]]:
    j = jsonlib.loads(raw)
    return {
        "ip":      j.get("ip"),
        "country": j.get("country_code") or j.get("country"),
        "region":  j.get("region"),
        "city":    j.get("city"),
        "org":     j.get("org"),
        "asn":     j.get("asn"),
    }


def _parse_plain(raw: str) -> Dict[str, Optional[str]]:
    return {"ip": raw.strip(), "country": None, "region": None, "city": None, "org": None, "asn": None}


PARSERS = {
    "ipinfo":   _parse_ipinfo,
    "ifconfig": _parse_ifconfigco,
    "ipapi":    _parse_ipapi,
    "plain":    _parse_plain,
}


def query_source(src: Source, timeout: float) -> IpResult:
    try:
        raw = _http_get(src.url, timeout)
        fields = PARSERS[src.parser](raw)
        return IpResult(
            source=src.name,
            ok=True,
            family=src.family,
            **{k: fields.get(k) for k in ("ip", "country", "region", "city", "org", "asn")},
        )
    except urllib.error.HTTPError as e:
        return IpResult(source=src.name, ok=False, error=f"HTTP {e.code}", family=src.family)
    except (urllib.error.URLError, TimeoutError) as e:
        msg = str(getattr(e, "reason", e)) or e.__class__.__name__
        return IpResult(source=src.name, ok=False, error=msg, family=src.family)
    except Exception as e:  # noqa: BLE001 — 网络/解析异常都归为查询失败
        return IpResult(source=src.name, ok=False, error=f"{e.__class__.__name__}: {e}", family=src.family)


# ---------- 本地接口 ----------

@dataclass
class LocalIface:
    name: str
    status: str          # "active" / "inactive"
    v4: List[str]
    v6: List[str]
    mac: Optional[str]


_IFCONFIG_BLOCK_RE = re.compile(r"^(\S+):\s+flags=", re.MULTILINE)


def parse_ifconfig() -> List[LocalIface]:
    """解析 ifconfig 输出（macOS / BSD 风格；Linux 也大致兼容）。"""
    try:
        raw = subprocess.run(
            ["ifconfig"], capture_output=True, check=False, timeout=5,
        ).stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    blocks: List[str] = []
    matches = list(_IFCONFIG_BLOCK_RE.finditer(raw))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        blocks.append(raw[start:end])

    ifaces: List[LocalIface] = []
    for blk in blocks:
        first = blk.splitlines()[0]
        name = first.split(":", 1)[0]
        status = "active"
        m_status = re.search(r"status:\s*(\S+)", blk)
        if m_status:
            status = m_status.group(1)
        elif "RUNNING" not in first:
            status = "inactive"

        v4 = re.findall(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", blk)
        v6 = re.findall(r"\binet6\s+([0-9a-fA-F:]+)", blk)
        mac = None
        m_mac = re.search(r"\bether\s+([0-9a-f:]+)", blk)
        if m_mac:
            mac = m_mac.group(1)

        ifaces.append(LocalIface(name=name, status=status, v4=v4, v6=v6, mac=mac))
    return ifaces


def parse_default_gateway() -> Optional[str]:
    # macOS: route -n get default
    try:
        out = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
        m = re.search(r"gateway:\s*(\S+)", out)
        if m:
            return m.group(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Linux fallback: ip route
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
        m = re.search(r"default via (\S+)", out)
        if m:
            return m.group(1)
    except FileNotFoundError:
        pass
    return None


def parse_dns_servers() -> List[str]:
    servers: List[str] = []
    # macOS
    try:
        out = subprocess.run(
            ["scutil", "--dns"], capture_output=True, check=False, timeout=3,
        ).stdout.decode("utf-8", errors="replace")
        for m in re.finditer(r"nameserver\[\d+\]\s*:\s*(\S+)", out):
            ip = m.group(1)
            if ip not in servers:
                servers.append(ip)
        if servers:
            return servers
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # /etc/resolv.conf 兜底
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] not in servers:
                        servers.append(parts[1])
    except OSError:
        pass
    return servers


# ---------- 渲染 ----------

def _is_global_v6(addr: str) -> bool:
    base = addr.split("%", 1)[0]
    try:
        ip = ipaddress.IPv6Address(base)
    except ValueError:
        return False
    return ip.is_global


def _shorten_org(org: Optional[str]) -> str:
    if not org:
        return f"{DIM}-{RESET}"
    return org.strip()


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _disp_w(s: str) -> int:
    bare = _ANSI_RE.sub("", s)
    w = 0
    for ch in bare:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def _pad(s: str, width: int) -> str:
    extra = width - _disp_w(s)
    return s + (" " * extra if extra > 0 else "")


def render_public(results: List[IpResult]) -> None:
    print(f"{BOLD}公网 IP{RESET}")
    print(f"  {DIM}{_pad('源', 14)}{_pad('IP', 18)}{_pad('位置', 30)}ISP / ASN{RESET}")

    v4_ips: List[str] = []
    v6_ips: List[str] = []
    for r in results:
        if r.ok and r.ip:
            (v4_ips if r.family == "v4" else v6_ips).append(r.ip)
    v4_unique = set(v4_ips)
    v6_unique = set(v6_ips)

    for r in results:
        if not r.ok:
            ip_part = f"{RED}× {r.error}{RESET}"
            loc = ""
            org = ""
        else:
            inconsistent = (
                (r.family == "v4" and len(v4_unique) > 1)
                or (r.family == "v6" and len(v6_unique) > 1)
            )
            ip_color = YELLOW if inconsistent else GREEN
            ip_part = f"{ip_color}{r.ip or '-'}{RESET}"
            loc_parts = [p for p in (r.country, r.region, r.city) if p]
            loc = "/".join(loc_parts) if loc_parts else f"{DIM}-{RESET}"
            org = _shorten_org(r.org)
            if r.asn and r.asn not in (org or ""):
                org = f"{org} {DIM}({r.asn}){RESET}"

        print(f"  {_pad(r.source, 14)}{_pad(ip_part, 18)}{_pad(loc, 30)}{org}")

    if len(v4_unique) > 1:
        print(f"  {YELLOW}⚠ IPv4 多源结果不一致：{', '.join(sorted(v4_unique))}{RESET}")
    if len(v6_unique) > 1:
        print(f"  {YELLOW}⚠ IPv6 多源结果不一致：{', '.join(sorted(v6_unique))}{RESET}")


def render_local(ifaces: List[LocalIface], gateway: Optional[str], dns: List[str], all_ifaces: bool) -> None:
    print()
    print(f"{BOLD}本机网卡{RESET}")
    if not ifaces:
        print(f"  {DIM}(未获取到 ifconfig 输出){RESET}")
        return

    shown = 0
    for ifc in ifaces:
        # 默认只显示有 IP 的活跃网卡，过滤 lo* 和无 IP 的
        if not all_ifaces:
            if ifc.name.startswith("lo"):
                continue
            if ifc.status != "active" and ifc.status != "running":
                # 一些 macOS 网卡没 status 字段；用 RUNNING flag 已处理
                if not (ifc.v4 or ifc.v6):
                    continue
            if not ifc.v4 and not ifc.v6:
                continue

        shown += 1
        status_color = GREEN if ifc.status == "active" else GRAY
        head = f"  {CYAN}{ifc.name}{RESET}  {status_color}{ifc.status}{RESET}"
        if ifc.mac:
            head += f"  {DIM}MAC {ifc.mac}{RESET}"
        print(head)
        for v in ifc.v4:
            print(f"      {GREEN}v4{RESET}  {v}")
        for v in ifc.v6:
            tag = f"{GREEN}v6{RESET}" if _is_global_v6(v) else f"{DIM}v6{RESET}"
            color = "" if _is_global_v6(v) else DIM
            print(f"      {tag}  {color}{v}{RESET}")

    if shown == 0:
        print(f"  {DIM}(无活跃网卡；用 -a 查看全部){RESET}")

    print()
    print(f"{BOLD}路由 / DNS{RESET}")
    gw = gateway or f"{DIM}-{RESET}"
    print(f"  默认网关  {gw}")
    if dns:
        print(f"  DNS       {', '.join(dns)}")
    else:
        print(f"  DNS       {DIM}-{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ipx",
        description="公网 IP（多源对比）+ 本机网卡 + 网关 + DNS",
    )
    parser.add_argument("-4", "--v4-only", action="store_true", help="只查 IPv4")
    parser.add_argument("-6", "--v6-only", action="store_true", help="只查 IPv6")
    parser.add_argument("-l", "--local-only", action="store_true", help="只显示本机信息（不查公网）")
    parser.add_argument("-p", "--public-only", action="store_true", help="只显示公网信息")
    parser.add_argument("-a", "--all", action="store_true", help="显示所有网卡（含 lo / 无 IP / 非活跃）")
    parser.add_argument("-t", "--timeout", type=float, default=5.0, help="单源超时秒（默认 5）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    public_results: List[IpResult] = []
    if not args.local_only:
        sources = list(SOURCES)
        if args.v4_only:
            sources = [s for s in sources if s.family == "v4"]
        elif args.v6_only:
            sources = [s for s in sources if s.family == "v6"]

        with ThreadPoolExecutor(max_workers=len(sources)) as ex:
            futures = {ex.submit(query_source, s, args.timeout): s for s in sources}
            results_map: Dict[str, IpResult] = {}
            for fut in as_completed(futures):
                r = fut.result()
                results_map[r.source] = r
        # 保持原顺序
        public_results = [results_map[s.name] for s in sources if s.name in results_map]

    ifaces: List[LocalIface] = []
    gateway: Optional[str] = None
    dns: List[str] = []
    if not args.public_only:
        ifaces = parse_ifconfig()
        gateway = parse_default_gateway()
        dns = parse_dns_servers()

    if args.json:
        out = {
            "public": [r.__dict__ for r in public_results],
            "local": {
                "interfaces": [ifc.__dict__ for ifc in ifaces],
                "gateway": gateway,
                "dns": dns,
            },
        }
        print(jsonlib.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if not args.local_only:
        render_public(public_results)
    if not args.public_only:
        render_local(ifaces, gateway, dns, args.all)

    # 全部失败时退出码非 0
    if not args.local_only and public_results and not any(r.ok for r in public_results):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
