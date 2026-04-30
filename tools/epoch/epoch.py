#!/usr/bin/env python3
"""epoch - 时间戳 ↔ 日期双向转换。

输入识别规则:
  - 空 / "now"            → 当前时间
  - 纯数字 10 位          → Unix 秒
  - 纯数字 13 位          → Unix 毫秒
  - 纯数字 16 位          → Unix 微秒
  - 纯数字 19 位          → Unix 纳秒
  - 其他纯数字            → 按 Unix 秒解释（带提示）
  - 含 '-' 或 '/'         → 日期字符串，依次尝试常见格式

输出: Unix 秒/毫秒/微秒, ISO 8601, UTC, 北京时间, 本地时间, RFC 2822, 相对时间。
也支持 -f 自定义输出（strftime 字符串或别名）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Tuple

try:
    from zoneinfo import ZoneInfo

    BJ_TZ = ZoneInfo("Asia/Shanghai")
except ImportError:  # Python < 3.9
    BJ_TZ = timezone(timedelta(hours=8))

LOCAL_TZ = datetime.now().astimezone().tzinfo

# ANSI 配色（NO_COLOR / EPOCH_FORCE_COLOR / TTY 检测）
_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("EPOCH_FORCE_COLOR") or sys.stdout.isatty())
)
DIM = "\x1b[2m" if _USE_COLOR else ""
CYAN = "\x1b[36m" if _USE_COLOR else ""
GREEN = "\x1b[32m" if _USE_COLOR else ""
YELLOW = "\x1b[33m" if _USE_COLOR else ""
RESET = "\x1b[0m" if _USE_COLOR else ""

# -f 别名 → (strftime 字符串, 默认时区, 描述)
# 时区为 None 表示直接产生数字（不走 strftime）
FORMAT_ALIASES: dict[str, Tuple[str | None, str | None, str]] = {
    "iso":       ("%Y-%m-%dT%H:%M:%SZ",      "utc",   "ISO 8601 UTC"),
    "iso-ms":    ("%Y-%m-%dT%H:%M:%S.%f%z",  "local", "ISO 8601 含毫秒+时区"),
    "iso-local": ("%Y-%m-%dT%H:%M:%S%z",     "local", "ISO 8601 含本地时区"),
    "iso-bj":    ("%Y-%m-%dT%H:%M:%S%z",     "bj",    "ISO 8601 含北京时区"),
    "rfc":       ("%a, %d %b %Y %H:%M:%S %z", "utc",  "RFC 2822"),
    "date":      ("%Y-%m-%d",                "bj",    "日期"),
    "time":      ("%H:%M:%S",                "bj",    "时间"),
    "datetime":  ("%Y-%m-%d %H:%M:%S",       "bj",    "日期时间"),
    "compact":   ("%Y%m%d%H%M%S",            "bj",    "紧凑日期时间"),
    "sec":       (None,                       None,   "Unix 秒"),
    "ms":        (None,                       None,   "Unix 毫秒"),
    "us":        (None,                       None,   "Unix 微秒"),
    "ns":        (None,                       None,   "Unix 纳秒"),
}


def parse_input(raw: str) -> Tuple[datetime, str]:
    """返回 (utc_datetime, 输入识别标签)。失败抛 ValueError。"""
    s = raw.strip()
    if not s or s.lower() in ("now", "当前", "现在"):
        return datetime.now(timezone.utc), "当前时间"

    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        digits = len(s.lstrip("-").split(".")[0])
        n = float(s)
        if digits <= 10:
            ts, label = n, f"Unix 秒（{digits} 位）"
        elif digits == 13:
            ts, label = n / 1_000, "Unix 毫秒（13 位）"
        elif digits == 16:
            ts, label = n / 1_000_000, "Unix 微秒（16 位）"
        elif digits == 19:
            ts, label = n / 1_000_000_000, "Unix 纳秒（19 位）"
        else:
            ts, label = n, f"未知位数（{digits} 位，按 Unix 秒解释）"
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc), label
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(f"时间戳超出可表示范围: {exc}") from exc

    s_norm = s.replace("Z", "+0000")
    formats = [
        ("%Y-%m-%dT%H:%M:%S.%f%z", "ISO 8601（含微秒+时区）"),
        ("%Y-%m-%dT%H:%M:%S%z",    "ISO 8601（含时区）"),
        ("%Y-%m-%dT%H:%M:%S.%f",   "ISO 8601（无时区，按本地解释）"),
        ("%Y-%m-%dT%H:%M:%S",      "ISO 8601（无时区，按本地解释）"),
        ("%Y-%m-%d %H:%M:%S.%f",   "日期时间（按本地解释）"),
        ("%Y-%m-%d %H:%M:%S",      "日期时间（按本地解释）"),
        ("%Y-%m-%d %H:%M",         "日期时间（按本地解释）"),
        ("%Y-%m-%d",               "日期（按本地解释）"),
        ("%Y/%m/%d %H:%M:%S",      "日期时间（按本地解释）"),
        ("%Y/%m/%d %H:%M",         "日期时间（按本地解释）"),
        ("%Y/%m/%d",               "日期（按本地解释）"),
        ("%Y%m%d",                 "紧凑日期（按本地解释）"),
        ("%Y%m%dT%H%M%S",          "紧凑日期时间（按本地解释）"),
    ]
    for fmt, label in formats:
        try:
            dt = datetime.strptime(s_norm, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=LOCAL_TZ)
            return dt.astimezone(timezone.utc), label
        except ValueError:
            continue

    raise ValueError(f"无法识别的输入: {raw!r}")


def relative(dt_utc: datetime) -> str:
    now = datetime.now(timezone.utc)
    secs = int((now - dt_utc).total_seconds())
    suffix = "前" if secs >= 0 else "后"
    a = abs(secs)
    if a < 1:
        return "刚刚"
    if a < 60:
        return f"{a} 秒{suffix}"
    if a < 3600:
        return f"{a // 60} 分钟{suffix}"
    if a < 86400:
        return f"{a // 3600} 小时{suffix}"
    if a < 86400 * 30:
        return f"{a // 86400} 天{suffix}"
    if a < 86400 * 365:
        return f"{a // 86400 // 30} 个月{suffix}"
    return f"{a // 86400 // 365} 年{suffix}"


def _to_tz(dt_utc: datetime, tz_name: str) -> datetime:
    if tz_name == "utc":
        return dt_utc.astimezone(timezone.utc)
    if tz_name in ("bj", "beijing"):
        return dt_utc.astimezone(BJ_TZ)
    return dt_utc.astimezone(LOCAL_TZ)


def render_format(dt_utc: datetime, fmt: str, tz: str) -> str:
    """按 -f 输出单一格式。fmt 可以是别名或 strftime 字符串。"""
    if fmt in FORMAT_ALIASES:
        aliased_fmt, alias_tz, _ = FORMAT_ALIASES[fmt]
        if aliased_fmt is None:
            secs = dt_utc.timestamp()
            return {
                "sec": str(int(secs)),
                "ms":  str(int(secs * 1_000)),
                "us":  str(int(secs * 1_000_000)),
                "ns":  str(int(secs * 1_000_000_000)),
            }[fmt]
        # 用户显式给的 --tz 优先于别名默认
        actual_tz = tz if tz != "default" else (alias_tz or "bj")
        return _to_tz(dt_utc, actual_tz).strftime(aliased_fmt)

    actual_tz = tz if tz != "default" else "bj"
    return _to_tz(dt_utc, actual_tz).strftime(fmt)


def render_table(dt_utc: datetime, raw: str, label: str) -> None:
    secs = dt_utc.timestamp()
    bj = dt_utc.astimezone(BJ_TZ)
    local = dt_utc.astimezone(LOCAL_TZ)

    rows = [
        ("北京时间",  bj.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("本地时间",  local.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("UTC",       dt_utc.strftime("%Y-%m-%d %H:%M:%S")),
        ("ISO 8601",  dt_utc.isoformat().replace("+00:00", "Z")),
        ("RFC 2822",  dt_utc.strftime("%a, %d %b %Y %H:%M:%S +0000")),
        ("相对",      relative(dt_utc)),
        ("Unix 秒",   f"{int(secs)}"),
        ("Unix 毫秒", f"{int(secs * 1000)}"),
        ("Unix 微秒", f"{int(secs * 1_000_000)}"),
    ]

    def disp_width(s: str) -> int:
        return sum(2 if ord(c) > 127 else 1 for c in s)

    label_w = max(disp_width(k) for k, _ in rows)
    print(f"{DIM}输入:{RESET} {raw or 'now'}  {DIM}→{RESET}  {YELLOW}{label}{RESET}")
    print()
    for k, v in rows:
        pad = " " * (label_w - disp_width(k))
        print(f"  {CYAN}{k}{RESET}{pad}  {GREEN}{v}{RESET}")


def list_aliases() -> None:
    print("可用的 -f 别名:")
    for name, (_fmt, tz, desc) in FORMAT_ALIASES.items():
        tz_label = f"[{tz}]" if tz else "[数字]"
        print(f"  {name:<10} {tz_label:<8} {desc}")
    print("\n也可以传任意 strftime 字符串，例如:")
    print("  epoch 1714492800 -f '%Y/%m/%d %H:%M'")


def read_clipboard() -> str:
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"读取剪贴板失败: {exc}") from exc
    return result.stdout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="epoch",
        description="时间戳 ↔ 日期双向转换",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="*", help="时间戳或日期字符串；不传则用 now")
    p.add_argument(
        "-f", "--format",
        help="自定义输出（别名 iso/sec/ms/date/datetime... 或 strftime 字符串）",
    )
    p.add_argument(
        "--tz",
        choices=["default", "bj", "beijing", "local", "utc"],
        default="default",
        help="-f 用的时区（默认按别名各自的默认；通用 strftime 默认北京）",
    )
    p.add_argument("-c", "--clip", action="store_true", help="从剪贴板读取输入")
    p.add_argument(
        "--list-formats",
        action="store_true",
        help="列出所有 -f 可用的别名",
    )
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    if args.list_formats:
        list_aliases()
        return 0

    if args.clip:
        raw = read_clipboard()
    elif args.input:
        raw = " ".join(args.input)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = ""
    raw = raw.strip()

    try:
        dt_utc, label = parse_input(raw)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        print(
            "  支持示例: 1714492800 / 1714492800000 / 2024-04-30 15:30 / now",
            file=sys.stderr,
        )
        return 1

    if args.format:
        try:
            print(render_format(dt_utc, args.format, args.tz))
        except (ValueError, KeyError) as exc:
            print(f"✗ 格式化失败: {exc}", file=sys.stderr)
            return 1
        return 0

    render_table(dt_utc, raw, label)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
