#!/usr/bin/env python3
"""aix - Claude Code token 用量统计。

数据源：~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
每个 assistant 消息行带 usage（input/output/cache_read/cache_creation）+ model + timestamp。

支持按 day / model / project / session 聚合，输出表格 + 条形图。
首次扫描后会把每文件的聚合结果缓存到 ~/.cache/aix/cache.json，
之后只重解析 size/mtime 变化的文件。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

PROJECTS_DIR = Path.home() / ".claude" / "projects"
CACHE_DIR = Path.home() / ".cache" / "aix"
CACHE_FILE = CACHE_DIR / "cache.json"
CACHE_VERSION = 2

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("AIX_FORCE_COLOR") or sys.stdout.isatty())
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


# ---------- 解析 ----------

@dataclass
class Row:
    date: str        # YYYY-MM-DD（本地时区）
    model: str
    project: str     # 反推出的 cwd（短名）
    session: str     # session-id
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_create


# 每个文件解析出的聚合 tuple，写进缓存
# (date, model, project, session, input, output, cache_read, cache_create)
FileAgg = List[Tuple[str, str, str, str, int, int, int, int]]


def decode_project(folder_name: str) -> str:
    """`-Users-quzhihao-Downloads-tools` → `/Users/quzhihao/Downloads/tools`。

    Claude Code 用 '-' 替换路径里的 '/'。我们简单还原；遇到原本就有 '-'
    的目录名做不到完美还原，但展示足够。
    """
    if folder_name.startswith("-"):
        return "/" + folder_name[1:].replace("-", "/")
    return folder_name


def short_project(path: str, max_len: int = 40) -> str:
    """缩短显示：~ 替换 home，过长保留尾部。"""
    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1):]


def parse_file(path: Path) -> FileAgg:
    """流式读 jsonl，对每个 assistant 消息抽 usage。"""
    bucket: Dict[Tuple[str, str, str, str], List[int]] = defaultdict(lambda: [0, 0, 0, 0])
    project = decode_project(path.parent.name)
    session = path.stem

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip()
                if not line or '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage") or {}
                if not usage:
                    continue
                model = msg.get("model") or "unknown"
                ts = obj.get("timestamp")
                date = _ts_to_local_date(ts)

                ci = int(usage.get("cache_creation_input_tokens") or 0)
                cr = int(usage.get("cache_read_input_tokens") or 0)
                inp = int(usage.get("input_tokens") or 0)
                out = int(usage.get("output_tokens") or 0)

                key = (date, model, project, session)
                b = bucket[key]
                b[0] += inp
                b[1] += out
                b[2] += cr
                b[3] += ci
    except OSError:
        return []

    return [
        (k[0], k[1], k[2], k[3], v[0], v[1], v[2], v[3])
        for k, v in bucket.items()
    ]


def _ts_to_local_date(ts: Optional[str]) -> str:
    if not ts:
        return "1970-01-01"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return "1970-01-01"
    return dt.astimezone().strftime("%Y-%m-%d")


# ---------- 缓存 ----------

def load_cache() -> Dict:
    if not CACHE_FILE.exists():
        return {"version": CACHE_VERSION, "files": {}}
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": CACHE_VERSION, "files": {}}
    if data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "files": {}}
    return data


def save_cache(cache: Dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    tmp.replace(CACHE_FILE)


def collect_rows(verbose: bool = False) -> List[Row]:
    if not PROJECTS_DIR.exists():
        return []

    cache = load_cache()
    file_cache: Dict[str, Dict] = cache.get("files", {})
    new_file_cache: Dict[str, Dict] = {}

    rows: List[Row] = []
    parsed = 0
    cached = 0

    for path in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        sig = {"size": st.st_size, "mtime": int(st.st_mtime)}
        old = file_cache.get(key)
        if old and old.get("size") == sig["size"] and old.get("mtime") == sig["mtime"]:
            agg = old.get("agg") or []
            cached += 1
        else:
            agg = parse_file(path)
            parsed += 1
        new_file_cache[key] = {**sig, "agg": agg}
        for tup in agg:
            rows.append(Row(*tup))

    save_cache({"version": CACHE_VERSION, "files": new_file_cache})
    if verbose:
        print(f"{DIM}解析 {parsed} 文件，缓存命中 {cached}{RESET}", file=sys.stderr)
    return rows


# ---------- 聚合 ----------

@dataclass
class Bucket:
    label: str
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0

    def add(self, r: Row) -> None:
        self.input += r.input
        self.output += r.output
        self.cache_read += r.cache_read
        self.cache_create += r.cache_create

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_create

    @property
    def total_input_like(self) -> int:
        return self.input + self.cache_read + self.cache_create

    @property
    def cache_hit(self) -> float:
        denom = self.total_input_like
        return self.cache_read / denom if denom else 0.0


def parse_since(spec: Optional[str]) -> Optional[str]:
    """'7d' / '30d' / 'YYYY-MM-DD' / 'all' → 起始日期 YYYY-MM-DD（本地）。"""
    if not spec or spec == "all":
        return None
    spec = spec.strip().lower()
    if spec.endswith("d") and spec[:-1].isdigit():
        days = int(spec[:-1])
        d = datetime.now().astimezone() - timedelta(days=days - 1)  # 含今天
        return d.strftime("%Y-%m-%d")
    if len(spec) == 10 and spec[4] == "-" and spec[7] == "-":
        return spec
    raise SystemExit(f"无法解析 --since: {spec}（用 7d / 30d / 2026-01-01 / all）")


def filter_rows(rows: List[Row], since: Optional[str], project_filter: Optional[str], model_filter: Optional[str]) -> List[Row]:
    out = rows
    if since:
        out = [r for r in out if r.date >= since]
    if project_filter:
        pf = project_filter.lower()
        out = [r for r in out if pf in r.project.lower()]
    if model_filter:
        mf = model_filter.lower()
        out = [r for r in out if mf in r.model.lower()]
    return out


def aggregate(rows: List[Row], dim: str) -> List[Bucket]:
    buckets: Dict[str, Bucket] = {}
    for r in rows:
        if dim == "day":
            key = r.date
        elif dim == "model":
            key = r.model
        elif dim == "project":
            key = short_project(r.project)
        elif dim == "session":
            key = r.session[:8]
        else:
            raise SystemExit(f"未知聚合维度: {dim}")
        b = buckets.get(key)
        if b is None:
            b = Bucket(label=key)
            buckets[key] = b
        b.add(r)
    return list(buckets.values())


# ---------- 渲染 ----------

def fmt_num(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}G"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def render_bar(ratio: float, width: int) -> str:
    filled = int(round(ratio * width))
    empty = width - filled
    if _USE_COLOR:
        return f"{CYAN}{'█' * filled}{RESET}{DIM}{'░' * empty}{RESET}"
    return "█" * filled + "░" * empty


def render_table(buckets: List[Bucket], dim: str, top: int, sort: str) -> None:
    if not buckets:
        print(f"{DIM}(没有数据){RESET}")
        return

    if sort == "label":
        buckets.sort(key=lambda b: b.label)
    else:
        buckets.sort(key=lambda b: b.total, reverse=True)
    if dim == "day" and sort == "total":
        # 日期维度默认升序更直观
        buckets.sort(key=lambda b: b.label)
    if top > 0 and len(buckets) > top:
        buckets = buckets[:top]

    label_w = max(len(b.label) for b in buckets)
    label_w = min(max(label_w, 8), 40)
    max_total = max(b.total for b in buckets) or 1

    headers = [
        f"{dim:<{label_w}}",
        f"{'in':>8}",
        f"{'out':>8}",
        f"{'cache_r':>9}",
        f"{'cache_w':>9}",
        f"{'total':>9}",
        f"{'hit%':>6}",
        " bar",
    ]
    print(f"{DIM}{''.join(headers)}{RESET}")

    grand = Bucket(label="Σ")
    for b in buckets:
        grand.input += b.input
        grand.output += b.output
        grand.cache_read += b.cache_read
        grand.cache_create += b.cache_create

        lbl = b.label[:label_w]
        ratio = b.total / max_total
        bar = render_bar(ratio, 30)
        hit = f"{b.cache_hit * 100:5.1f}"
        total_color = _bar_color_for(b.total, max_total)
        print(
            f"{lbl:<{label_w}}"
            f"{fmt_num(b.input):>8}"
            f"{fmt_num(b.output):>8}"
            f"{fmt_num(b.cache_read):>9}"
            f"{fmt_num(b.cache_create):>9}"
            f"{total_color}{fmt_num(b.total):>9}{RESET}"
            f"{hit:>6} "
            f"{bar}"
        )

    sep = "─" * (label_w + 8 + 8 + 9 + 9 + 9 + 6 + 1 + 30)
    print(f"{DIM}{sep}{RESET}")
    print(
        f"{BOLD}{'Σ':<{label_w}}{RESET}"
        f"{fmt_num(grand.input):>8}"
        f"{fmt_num(grand.output):>8}"
        f"{fmt_num(grand.cache_read):>9}"
        f"{fmt_num(grand.cache_create):>9}"
        f"{BOLD}{fmt_num(grand.total):>9}{RESET}"
        f"{grand.cache_hit * 100:5.1f}%"
    )


def _bar_color_for(v: int, max_v: int) -> str:
    if max_v <= 0:
        return ""
    r = v / max_v
    if r >= 0.8:
        return RED
    if r >= 0.4:
        return YELLOW
    return GREEN


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="aix",
        description="Claude Code token 用量统计（读 ~/.claude/projects/）",
    )
    parser.add_argument(
        "-b", "--by",
        choices=["day", "model", "project", "session"],
        default="day",
        help="聚合维度（默认 day）",
    )
    parser.add_argument("-s", "--since", default="7d", help="时间范围：7d / 30d / 2026-01-01 / all（默认 7d）")
    parser.add_argument("-n", "--top", type=int, default=20, help="最多显示行数（默认 20，0=全部）")
    parser.add_argument("--sort", choices=["total", "label"], default="total", help="排序方式（默认 total 降序）")
    parser.add_argument("-p", "--project", help="过滤项目（子串匹配）")
    parser.add_argument("-m", "--model", help="过滤模型（子串匹配）")
    parser.add_argument("--watch", type=float, nargs="?", const=5.0, help="持续刷新（秒，默认 5）")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示缓存命中信息")
    parser.add_argument("--no-cache", action="store_true", help="忽略缓存全量重解析")
    args = parser.parse_args()

    since = parse_since(args.since)

    if args.no_cache and CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
        except OSError:
            pass

    def render_once() -> None:
        rows = collect_rows(verbose=args.verbose)
        rows = filter_rows(rows, since, args.project, args.model)
        buckets = aggregate(rows, args.by)
        head = f"{BOLD}aix{RESET} {DIM}by={args.by} since={args.since}"
        if args.project:
            head += f" project~={args.project}"
        if args.model:
            head += f" model~={args.model}"
        head += f"{RESET}"
        print(head)
        render_table(buckets, args.by, args.top, args.sort)

    if args.watch:
        try:
            while True:
                # 清屏 + 光标归位
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.flush()
                render_once()
                print(f"\n{DIM}↻ 每 {args.watch:g}s 刷新（Ctrl-C 退出）{RESET}")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print()
            return 0
    else:
        render_once()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
