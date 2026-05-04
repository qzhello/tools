#!/usr/bin/env python3
"""certx - HTTPS 证书检查。

通过 openssl s_client 拉取证书链，逐张解析（subject / issuer / SAN /
有效期 / 指纹），高亮即将过期或已过期的证书。
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("CERTX_FORCE_COLOR") or sys.stdout.isatty())
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


PEM_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)


def parse_target(s: str) -> Tuple[str, int]:
    # 接受 host / host:port / https://host / https://host:port/path
    s = s.strip()
    if s.startswith("https://"):
        s = s[8:]
    if s.startswith("http://"):
        s = s[7:]
    s = s.split("/")[0]
    if s.startswith("[") and "]" in s:
        # [ipv6]:port
        end = s.index("]")
        host = s[1:end]
        rest = s[end + 1:]
        port = int(rest.lstrip(":")) if rest else 443
        return host, port
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return s, 443
    return s, 443


def s_client(host: str, port: int, sni: Optional[str], timeout: int) -> Tuple[str, str, int]:
    cmd = [
        "openssl", "s_client",
        "-connect", f"{host}:{port}",
        "-servername", sni or host,
        "-showcerts",
    ]
    try:
        proc = subprocess.run(
            cmd, input=b"", capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        sys.exit(f"✗ 连接 {host}:{port} 超时（{timeout}s）")
    return (
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
        proc.returncode,
    )


def x509_dump(pem: str) -> str:
    cmd = [
        "openssl", "x509", "-noout",
        "-subject", "-issuer", "-startdate", "-enddate",
        "-serial", "-fingerprint", "-sha256",
        "-ext", "subjectAltName",
    ]
    try:
        proc = subprocess.run(
            cmd, input=pem.encode(), capture_output=True, check=False,
        )
    except FileNotFoundError:
        sys.exit("✗ 找不到 openssl")
    return proc.stdout.decode("utf-8", errors="replace")


def parse_dn(dn: str) -> Dict[str, str]:
    """解析 'CN = example.com, O = ACME, C = US' 风格的 DN。"""
    out: Dict[str, str] = {}
    # 兼容老版（slash 分隔）和新版（comma 分隔）
    if dn.startswith("/"):
        parts = [p for p in dn.split("/") if p]
    else:
        parts = [p.strip() for p in dn.split(",")]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_x509_dump(text: str) -> Dict:
    info: Dict = {"sans": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("subject="):
            info["subject"] = parse_dn(s[len("subject="):].strip())
        elif s.startswith("issuer="):
            info["issuer"] = parse_dn(s[len("issuer="):].strip())
        elif s.startswith("notBefore="):
            info["not_before"] = s[len("notBefore="):].strip()
        elif s.startswith("notAfter="):
            info["not_after"] = s[len("notAfter="):].strip()
        elif s.startswith("serial="):
            info["serial"] = s[len("serial="):].strip()
        elif "Fingerprint=" in s:
            info["fingerprint"] = s.split("=", 1)[1].strip()
        elif "Subject Alternative Name" in s:
            # 下一行（可能多行）开始是 DNS:foo, DNS:bar
            j = i + 1
            sans: List[str] = []
            while j < len(lines):
                t = lines[j].strip()
                if not t or ":" not in t or "=" in t.split()[0]:
                    break
                if t.startswith(("DNS:", "IP Address:", "URI:", "email:")):
                    for tok in t.split(","):
                        tok = tok.strip()
                        if tok:
                            sans.append(tok)
                    j += 1
                else:
                    break
            info["sans"] = sans
            i = j - 1
        i += 1
    return info


def parse_openssl_date(s: str) -> Optional[datetime]:
    # "Apr 15 23:59:59 2024 GMT"
    s = s.strip()
    fmt = "%b %d %H:%M:%S %Y %Z"
    try:
        dt = datetime.strptime(s, fmt)
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        # 兼容某些老 openssl 输出 "GMT" 之外的形式
        try:
            return datetime.strptime(s.replace(" GMT", ""), "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def days_between(a: datetime, b: datetime) -> int:
    return int((a - b).total_seconds() // 86400)


def color_for_days(days: int) -> str:
    if days < 0:
        return RED
    if days < 14:
        return RED
    if days < 30:
        return YELLOW
    return GREEN


def parse_session_info(out: str) -> Dict[str, str]:
    """从 s_client 输出里挖 TLS 协议 / cipher / 验证结果。"""
    info: Dict[str, str] = {}
    m = re.search(r"^\s*Protocol\s*:\s*(\S+)", out, re.MULTILINE)
    if m:
        info["protocol"] = m.group(1)
    m = re.search(r"^\s*Cipher\s*:\s*(\S+)", out, re.MULTILINE)
    if m:
        info["cipher"] = m.group(1)
    m = re.search(r"^\s*Server certificate", out, re.MULTILINE)
    m = re.search(r"^\s*Verify return code:\s*(\d+)\s*\((.*?)\)", out, re.MULTILINE)
    if m:
        info["verify_code"] = m.group(1)
        info["verify_msg"] = m.group(2)
    return info


def cn_or_str(dn: Dict[str, str]) -> str:
    return dn.get("CN") or dn.get("O") or "?"


def fmt_cert(label: str, idx: int, cert: Dict, host: str, now: datetime) -> List[str]:
    lines: List[str] = []
    sub = cert.get("subject", {})
    iss = cert.get("issuer", {})
    nb = cert.get("not_before_dt")
    na = cert.get("not_after_dt")
    sans = cert.get("sans", [])

    # 状态行
    if na:
        days_left = days_between(na, now)
        if days_left < 0:
            status = f"{RED}✗ 已过期 {-days_left} 天{RESET}"
        else:
            status = f"{color_for_days(days_left)}剩余 {days_left} 天{RESET}"
            if days_left < 30:
                status += f"  {YELLOW}⚠ 即将过期{RESET}"
    else:
        status = f"{GRAY}—{RESET}"

    title = f"{BOLD}[{idx}] {label}{RESET}  {DIM}{cn_or_str(sub)}{RESET}"
    lines.append(title)

    rows = [
        ("Subject",   _format_dn(sub)),
        ("Issuer",    _format_dn(iss)),
        ("Valid",     _fmt_validity(cert)),
        ("Status",    status),
    ]
    if cert.get("serial"):
        rows.append(("Serial",  f"{DIM}{cert['serial']}{RESET}"))
    if cert.get("fingerprint"):
        rows.append(("SHA-256", f"{DIM}{cert['fingerprint']}{RESET}"))
    if sans:
        match_marker = ""
        if idx == 0:
            if any(_san_matches(s, host) for s in sans):
                match_marker = f"  {GREEN}✓ 匹配 {host}{RESET}"
            else:
                match_marker = f"  {RED}✗ 不匹配 {host}{RESET}"
        rows.append(("SAN", _fmt_sans(sans) + match_marker))

    label_w = max(len(k) for k, _ in rows)
    for k, v in rows:
        lines.append(f"    {CYAN}{k.ljust(label_w)}{RESET}  {v}")
    return lines


def _format_dn(dn: Dict[str, str]) -> str:
    if not dn:
        return f"{DIM}—{RESET}"
    parts = []
    for k in ("CN", "O", "OU", "C", "L", "ST"):
        if k in dn:
            parts.append(f"{k}={dn[k]}")
    extra = [f"{k}={v}" for k, v in dn.items() if k not in ("CN", "O", "OU", "C", "L", "ST")]
    return ", ".join(parts + extra)


def _fmt_validity(cert: Dict) -> str:
    nb = cert.get("not_before_dt")
    na = cert.get("not_after_dt")
    nb_s = nb.strftime("%Y-%m-%d") if nb else "?"
    na_s = na.strftime("%Y-%m-%d") if na else "?"
    return f"{nb_s}  →  {na_s}"


def _fmt_sans(sans: List[str]) -> str:
    if len(sans) <= 6:
        return ", ".join(sans)
    return ", ".join(sans[:6]) + f"{DIM} ... 还有 {len(sans) - 6} 项{RESET}"


def _san_matches(san: str, host: str) -> bool:
    # san like "DNS:example.com" or "DNS:*.example.com"
    if not san.startswith("DNS:"):
        return False
    pattern = san[4:].strip().lower()
    h = host.lower()
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".example.com"
        return h.endswith(suffix) and h.count(".") == pattern.count(".")
    return pattern == h


def render(host: str, port: int, certs: List[Dict], session: Dict[str, str],
           now: datetime) -> None:
    print(f"{BOLD}certx{RESET} {host}:{port}")
    print()

    # 概览
    if certs:
        leaf = certs[0]
        na = leaf.get("not_after_dt")
        if na:
            days = days_between(na, now)
            if days < 0:
                head = f"{RED}✗ 证书已过期 {-days} 天{RESET}"
            elif days < 14:
                head = f"{RED}⚠ 证书 {days} 天后过期{RESET}"
            elif days < 30:
                head = f"{YELLOW}⚠ 证书 {days} 天后过期{RESET}"
            else:
                head = f"{GREEN}✓ 证书有效（剩余 {days} 天）{RESET}"
            print(f"  {head}")

        verify = session.get("verify_msg", "")
        verify_code = session.get("verify_code", "")
        if verify_code == "0":
            print(f"  {GREEN}✓ 证书链验证通过{RESET}")
        elif verify:
            print(f"  {RED}✗ 证书链验证失败: {verify}{RESET}")
        print()

    # TLS 信息
    if session.get("protocol") or session.get("cipher"):
        print(f"  {CYAN}TLS{RESET}     {session.get('protocol', '?')}  "
              f"{DIM}{session.get('cipher', '')}{RESET}")
        print()

    # 每张证书
    for i, cert in enumerate(certs):
        if i == 0:
            label = "Leaf"
        elif i == len(certs) - 1:
            label = "Root" if certs[i].get("subject") == certs[i].get("issuer") else "Intermediate"
        else:
            label = "Intermediate"
        for line in fmt_cert(label, i, cert, host, now):
            print(line)
        print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="certx",
        description="HTTPS 证书检查（到期、SAN、链、TLS 版本）",
    )
    p.add_argument("target", help="主机或 host:port 或 https://... URL")
    p.add_argument("--sni", help="覆盖 SNI（默认与 host 相同）")
    p.add_argument("--timeout", type=int, default=8, help="连接超时秒数（默认 8）")
    p.add_argument("-j", "--json", action="store_true", help="JSON 输出")
    return p


def main(argv: List[str]) -> int:
    args = build_parser().parse_args(argv)

    host, port = parse_target(args.target)
    if not host:
        print("✗ 无法解析目标", file=sys.stderr)
        return 1

    out, err, rc = s_client(host, port, args.sni, args.timeout)
    if "errno" in err.lower() or ("connect:" in err.lower()):
        print(f"✗ 连接失败: {err.strip().splitlines()[0] if err.strip() else 'unknown'}",
              file=sys.stderr)
        return 1

    pems = PEM_RE.findall(out)
    if not pems:
        print(f"✗ 未拿到证书。openssl 输出：\n{(err or out).strip()[:500]}",
              file=sys.stderr)
        return 1

    certs: List[Dict] = []
    for pem in pems:
        info = parse_x509_dump(x509_dump(pem))
        info["not_before_dt"] = parse_openssl_date(info.get("not_before", ""))
        info["not_after_dt"] = parse_openssl_date(info.get("not_after", ""))
        certs.append(info)

    session = parse_session_info(out)
    now = datetime.now(timezone.utc)

    if args.json:
        # 用户可消费的字段（不带 datetime 对象）
        out_certs = []
        for c in certs:
            out_certs.append({
                "subject": c.get("subject", {}),
                "issuer": c.get("issuer", {}),
                "not_before": c.get("not_before"),
                "not_after": c.get("not_after"),
                "days_left": days_between(c["not_after_dt"], now) if c.get("not_after_dt") else None,
                "serial": c.get("serial"),
                "fingerprint": c.get("fingerprint"),
                "sans": c.get("sans", []),
            })
        print(jsonlib.dumps({
            "host": host,
            "port": port,
            "session": session,
            "certs": out_certs,
        }, ensure_ascii=False, indent=2))
        return 0

    render(host, port, certs, session, now)

    leaf = certs[0]
    if leaf.get("not_after_dt") and days_between(leaf["not_after_dt"], now) < 0:
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
