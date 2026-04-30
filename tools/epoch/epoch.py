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

输出: Unix 秒/毫秒/微秒, ISO 8601, UTC, 北京时间, 本地时间, RFC 2822, 相对时间
"""

import sys
import os
import re
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    BJ_TZ = ZoneInfo("Asia/Shanghai")
except ImportError:  # Python < 3.9
    BJ_TZ = timezone(timedelta(hours=8))

LOCAL_TZ = datetime.now().astimezone().tzinfo

# ANSI（仅 stderr/stdout 是 TTY 时；可被 NO_COLOR / EPOCH_FORCE_COLOR 覆盖）
_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("EPOCH_FORCE_COLOR") or sys.stdout.isatty())
)
DIM = "\x1b[2m" if _USE_COLOR else ""
BOLD = "\x1b[1m" if _USE_COLOR else ""
CYAN = "\x1b[36m" if _USE_COLOR else ""
GREEN = "\x1b[32m" if _USE_COLOR else ""
YELLOW = "\x1b[33m" if _USE_COLOR else ""
RESET = "\x1b[0m" if _USE_COLOR else ""


def parse_input(raw: str):
    """返回 (utc_datetime, 输入识别标签)。失败抛 ValueError。"""
    s = raw.strip()
    if not s or s.lower() in ("now", "当前", "现在"):
        return datetime.now(timezone.utc), "当前时间"

    # 纯数字 → Unix 时间戳
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

    # 日期字符串：依次试常见格式
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


def main(argv):
    raw = " ".join(argv) if argv else ""
    try:
        dt_utc, label = parse_input(raw)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        print("  支持示例: 1714492800 / 1714492800000 / 2024-04-30 15:30 / now", file=sys.stderr)
        return 1

    secs = dt_utc.timestamp()
    bj = dt_utc.astimezone(BJ_TZ)
    local = dt_utc.astimezone(LOCAL_TZ)

    rows = [
        ("北京时间",    bj.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("本地时间",    local.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("UTC",         dt_utc.strftime("%Y-%m-%d %H:%M:%S")),
        ("ISO 8601",    dt_utc.isoformat().replace("+00:00", "Z")),
        ("RFC 2822",    dt_utc.strftime("%a, %d %b %Y %H:%M:%S +0000")),
        ("相对",        relative(dt_utc)),
        ("Unix 秒",     f"{int(secs)}"),
        ("Unix 毫秒",   f"{int(secs * 1000)}"),
        ("Unix 微秒",   f"{int(secs * 1_000_000)}"),
    ]
    # 中文等宽对齐：用显示宽度而非字符数
    def disp_width(s):
        return sum(2 if ord(c) > 127 else 1 for c in s)
    label_w = max(disp_width(k) for k, _ in rows)

    print(f"{DIM}输入:{RESET} {raw or 'now'}  {DIM}→{RESET}  {YELLOW}{label}{RESET}")
    print()
    for k, v in rows:
        pad = " " * (label_w - disp_width(k))
        print(f"  {CYAN}{k}{RESET}{pad}  {GREEN}{v}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
