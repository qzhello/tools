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

CLAUDE_DIR = Path.home() / ".claude" / "projects"
CODEX_DIR = Path.home() / ".codex" / "sessions"
CACHE_DIR = Path.home() / ".cache" / "aix"
CACHE_FILE = CACHE_DIR / "cache.json"
CACHE_VERSION = 3

TOOLS_ALL = ["claude", "codex"]
TOOL_LABEL = {"claude": "Claude Code", "codex": "Codex"}

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
    tool: str        # "claude" / "codex"
    model: str
    project: str     # 反推出的 cwd
    session: str     # session-id
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_create


# 每个文件解析出的聚合 tuple，写进缓存
# (date, tool, model, project, session, input, output, cache_read, cache_create)
FileAgg = List[Tuple[str, str, str, str, str, int, int, int, int]]


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


def parse_claude_file(path: Path) -> FileAgg:
    """流式读 Claude Code 的 jsonl，对每个 assistant 消息抽 usage。"""
    bucket: Dict[Tuple[str, str, str, str, str], List[int]] = defaultdict(lambda: [0, 0, 0, 0])
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
                date = _ts_to_local_date(obj.get("timestamp"))

                ci = int(usage.get("cache_creation_input_tokens") or 0)
                cr = int(usage.get("cache_read_input_tokens") or 0)
                inp = int(usage.get("input_tokens") or 0)
                out = int(usage.get("output_tokens") or 0)

                key = (date, "claude", model, project, session)
                b = bucket[key]
                b[0] += inp
                b[1] += out
                b[2] += cr
                b[3] += ci
    except OSError:
        return []

    return [
        (k[0], k[1], k[2], k[3], k[4], v[0], v[1], v[2], v[3])
        for k, v in bucket.items()
    ]


def parse_codex_file(path: Path) -> FileAgg:
    """流式读 Codex 的 rollout-*.jsonl。

    Codex 把 token_count 事件里的 total_token_usage 作为整段会话的累计值。
    我们追踪累计差值（delta），按时间戳分配到当天，配上当时的 model 和 cwd。
    """
    bucket: Dict[Tuple[str, str, str, str, str], List[int]] = defaultdict(lambda: [0, 0, 0, 0])
    session = path.stem
    if session.startswith("rollout-"):
        # 取尾部 UUID
        session = session.rsplit("-", 5)[-1] if session.count("-") >= 5 else session

    cur_model = "unknown"
    cur_cwd: Optional[str] = None
    prev_input = prev_output = prev_cached = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                p = obj.get("payload") or {}
                if t == "session_meta":
                    cur_cwd = p.get("cwd") or cur_cwd
                elif t == "turn_context":
                    if p.get("cwd"):
                        cur_cwd = p["cwd"]
                    if p.get("model"):
                        cur_model = p["model"]
                elif t == "event_msg" and p.get("type") == "token_count":
                    info = p.get("info")
                    if not info:
                        continue
                    tot = info.get("total_token_usage") or {}
                    inp_total = int(tot.get("input_tokens") or 0)
                    out_total = int(tot.get("output_tokens") or 0)
                    cached_total = int(tot.get("cached_input_tokens") or 0)
                    # 把 reasoning_output 算到 output 里
                    reasoning = int(tot.get("reasoning_output_tokens") or 0)
                    out_total += reasoning

                    d_inp = max(0, inp_total - prev_input)
                    d_out = max(0, out_total - prev_output)
                    d_cached = max(0, cached_total - prev_cached)
                    if d_inp == 0 and d_out == 0 and d_cached == 0:
                        continue
                    # Codex 的 input_tokens 是包含 cached 的总额；拆开
                    d_inp_uncached = max(0, d_inp - d_cached)

                    project = cur_cwd or "/"
                    date = _ts_to_local_date(obj.get("timestamp"))
                    key = (date, "codex", cur_model, project, session)
                    b = bucket[key]
                    b[0] += d_inp_uncached
                    b[1] += d_out
                    b[2] += d_cached
                    # codex 没有显式的 cache_create
                    prev_input = inp_total
                    prev_output = out_total
                    prev_cached = cached_total
    except OSError:
        return []

    return [
        (k[0], k[1], k[2], k[3], k[4], v[0], v[1], v[2], v[3])
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


_TOOL_DISPATCH = {
    "claude": (CLAUDE_DIR, parse_claude_file),
    "codex":  (CODEX_DIR,  parse_codex_file),
}


def collect_rows(tools: Optional[List[str]] = None, verbose: bool = False) -> List[Row]:
    if tools is None:
        tools = TOOLS_ALL

    cache = load_cache()
    file_cache: Dict[str, Dict] = cache.get("files", {})
    new_file_cache: Dict[str, Dict] = {}

    rows: List[Row] = []
    parsed = 0
    cached = 0

    for tool in tools:
        root, parser = _TOOL_DISPATCH[tool]
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                st = path.stat()
            except OSError:
                continue
            key = f"{tool}:{path}"
            sig = {"size": st.st_size, "mtime": int(st.st_mtime)}
            old = file_cache.get(key)
            if old and old.get("size") == sig["size"] and old.get("mtime") == sig["mtime"]:
                agg = old.get("agg") or []
                cached += 1
            else:
                agg = parser(path)
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


def filter_rows(
    rows: List[Row],
    since: Optional[str],
    project_filter: Optional[str],
    model_filter: Optional[str],
    tool_filter: Optional[str] = None,
) -> List[Row]:
    out = rows
    if since:
        out = [r for r in out if r.date >= since]
    if tool_filter:
        out = [r for r in out if r.tool == tool_filter]
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
            key = f"{r.tool}:{r.model}"
        elif dim == "project":
            key = short_project(r.project)
        elif dim == "session":
            key = f"{r.tool}:{r.session[:8]}"
        elif dim == "tool":
            key = TOOL_LABEL.get(r.tool, r.tool)
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


# ---------- 交互式 TUI ----------

import curses

RANGES = ["1d", "7d", "30d", "90d", "all"]
DIMS = ["day", "model", "project", "session", "tool"]


@dataclass
class Picker:
    """弹出选择器状态。"""
    title: str
    field: str           # "project" / "model" / "tool"
    options: List[Tuple[str, int]]   # (display, total_tokens)
    cursor: int = 0
    query: str = ""

    def filtered(self) -> List[Tuple[int, str, int]]:
        q = self.query.lower()
        out = []
        for i, (label, total) in enumerate(self.options):
            if not q or q in label.lower():
                out.append((i, label, total))
        return out


@dataclass
class TuiState:
    rows: List[Row]
    dim_idx: int = 0
    range_idx: int = 1
    sort: str = "total"
    tool_filter: str = ""        # "" = 全部
    project_filter: str = ""
    model_filter: str = ""
    scroll: int = 0
    picker: Optional[Picker] = None
    status: str = ""

    @property
    def dim(self) -> str:
        return DIMS[self.dim_idx]

    @property
    def range(self) -> str:
        return RANGES[self.range_idx]


def _init_curses_colors() -> Dict[str, int]:
    curses.start_color()
    curses.use_default_colors()
    pairs = {
        "dim":     (8, -1) if curses.COLORS >= 16 else (curses.COLOR_WHITE, -1),
        "cyan":    (curses.COLOR_CYAN, -1),
        "green":   (curses.COLOR_GREEN, -1),
        "yellow":  (curses.COLOR_YELLOW, -1),
        "red":     (curses.COLOR_RED, -1),
        "magenta": (curses.COLOR_MAGENTA, -1),
        "blue":    (curses.COLOR_BLUE, -1),
        "reverse": (curses.COLOR_BLACK, curses.COLOR_CYAN),
    }
    out: Dict[str, int] = {}
    for i, (name, (fg, bg)) in enumerate(pairs.items(), start=1):
        try:
            curses.init_pair(i, fg, bg)
        except curses.error:
            pass
        out[name] = curses.color_pair(i)
    return out


def _safe_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x >= max_x:
            return
        # 截断
        avail = max_x - x - 1
        if avail <= 0:
            return
        win.addnstr(y, x, text, avail, attr)
    except curses.error:
        pass


def _bar_pair(c: Dict[str, int], v: int, max_v: int) -> int:
    if max_v <= 0:
        return c.get("green", 0)
    r = v / max_v
    if r >= 0.8:
        return c["red"]
    if r >= 0.4:
        return c["yellow"]
    return c["green"]


def _draw_tabs(win, y: int, label: str, items: List[str], active: int, c: Dict[str, int]) -> int:
    _safe_addstr(win, y, 0, f"{label}: ", c["dim"])
    x = len(label) + 2
    for i, it in enumerate(items):
        attr = c["reverse"] | curses.A_BOLD if i == active else 0
        text = f" {it} "
        _safe_addstr(win, y, x, text, attr)
        x += len(text) + 1
    return x


def _compute_table(state: TuiState) -> Tuple[List[Bucket], Bucket]:
    since = parse_since(state.range)
    rows = filter_rows(
        state.rows,
        since,
        state.project_filter or None,
        state.model_filter or None,
        state.tool_filter or None,
    )
    buckets = aggregate(rows, state.dim)
    if state.sort == "label":
        buckets.sort(key=lambda b: b.label)
    else:
        buckets.sort(key=lambda b: b.total, reverse=True)
        if state.dim == "day":
            buckets.sort(key=lambda b: b.label)
    grand = Bucket(label="Σ")
    for b in buckets:
        grand.input += b.input
        grand.output += b.output
        grand.cache_read += b.cache_read
        grand.cache_create += b.cache_create
    return buckets, grand


def _draw_table(win, top_y: int, buckets: List[Bucket], grand: Bucket, state: TuiState, c: Dict[str, int]) -> None:
    h, w = win.getmaxyx()
    if not buckets:
        _safe_addstr(win, top_y, 0, "(没有数据)", c["dim"])
        return

    label_w = max(len(b.label) for b in buckets)
    label_w = min(max(label_w, 8), 40)
    cols_fixed = label_w + 8 + 8 + 9 + 9 + 9 + 7  # 数字列宽
    bar_w = max(10, w - cols_fixed - 2)

    header = (
        f"{state.dim:<{label_w}}"
        f"{'in':>8}"
        f"{'out':>8}"
        f"{'cache_r':>9}"
        f"{'cache_w':>9}"
        f"{'total':>9}"
        f"{'hit%':>6}"
        " bar"
    )
    _safe_addstr(win, top_y, 0, header, c["cyan"] | curses.A_BOLD)
    # 表头下方分隔线
    _safe_addstr(win, top_y + 1, 0, "─" * (w - 1), c["cyan"])

    # 列表区高度（留出顶部表头+分隔=2 行，底部分隔+合计+帮助=3 行）
    list_h = h - top_y - 5
    if list_h <= 0:
        return

    visible = buckets[state.scroll : state.scroll + list_h]
    max_total = max(b.total for b in buckets) or 1

    for i, b in enumerate(visible):
        y = top_y + 2 + i
        lbl = b.label[:label_w]
        prefix = (
            f"{lbl:<{label_w}}"
            f"{fmt_num(b.input):>8}"
            f"{fmt_num(b.output):>8}"
            f"{fmt_num(b.cache_read):>9}"
            f"{fmt_num(b.cache_create):>9}"
        )
        _safe_addstr(win, y, 0, prefix)
        total_attr = _bar_pair(c, b.total, max_total) | curses.A_BOLD
        _safe_addstr(win, y, len(prefix), f"{fmt_num(b.total):>9}", total_attr)
        hit_str = f"{b.cache_hit * 100:5.1f} "
        _safe_addstr(win, y, len(prefix) + 9, hit_str)

        bar_x = len(prefix) + 9 + 6
        ratio = b.total / max_total
        filled = int(round(ratio * bar_w))
        empty = bar_w - filled
        _safe_addstr(win, y, bar_x, "█" * filled, c["cyan"])
        _safe_addstr(win, y, bar_x + filled, "░" * empty, c["dim"])

    # 合计行（紧贴帮助行上方）
    sum_y = h - 2
    sep_y = sum_y - 1
    _safe_addstr(win, sep_y, 0, "─" * (w - 1), c["dim"])
    sum_line = (
        f"{'Σ':<{label_w}}"
        f"{fmt_num(grand.input):>8}"
        f"{fmt_num(grand.output):>8}"
        f"{fmt_num(grand.cache_read):>9}"
        f"{fmt_num(grand.cache_create):>9}"
        f"{fmt_num(grand.total):>9}"
        f"{grand.cache_hit * 100:5.1f}%"
    )
    _safe_addstr(win, sum_y, 0, sum_line, curses.A_BOLD)


def _draw_footer(win, state: TuiState, c: Dict[str, int]) -> None:
    h, w = win.getmaxyx()
    y = h - 1
    # 反相背景做成「帮助条」，整行铺满，避免被忽略
    bar_attr = c["reverse"] | curses.A_BOLD
    _safe_addstr(win, y, 0, " " * (w - 1), bar_attr)
    if state.status:
        _safe_addstr(win, y, 1, state.status, c["reverse"] | curses.A_BOLD)
        return
    keys = " ↑↓ 滚动 │ Tab 维度 │ ←→ 范围 │ p 项目 │ m 模型 │ t 数据源 │ c 清空 │ s 排序 │ r 重扫 │ ? 帮助 │ q 退出 "
    _safe_addstr(win, y, 0, keys[: max(0, w - 1)], bar_attr)


def _draw_picker(win, picker: Picker, c: Dict[str, int]) -> None:
    """居中弹出列表，键盘可选；上方 query 行支持类型过滤。"""
    h, w = win.getmaxyx()
    items = picker.filtered()
    n_items = len(items)

    chrome_h = 7  # top + title + query + sep + ... + sep + hint + bot
    box_h = min(max(chrome_h + 3, n_items + chrome_h), h - 2)
    box_w = min(max(48, len(picker.title) + 8), w - 4)
    y0 = (h - box_h) // 2
    x0 = (w - box_w) // 2

    # 边框
    top    = "┌" + "─" * (box_w - 2) + "┐"
    mid    = "├" + "─" * (box_w - 2) + "┤"
    bot    = "└" + "─" * (box_w - 2) + "┘"
    blank  = "│" + " " * (box_w - 2) + "│"

    _safe_addstr(win, y0, x0, top, c["cyan"])
    title_line = f"│ {picker.title}".ljust(box_w - 1) + "│"
    _safe_addstr(win, y0 + 1, x0, title_line, c["cyan"] | curses.A_BOLD)
    query_text = f"│ 输入过滤: {picker.query}_".ljust(box_w - 1) + "│"
    _safe_addstr(win, y0 + 2, x0, query_text)
    _safe_addstr(win, y0 + 3, x0, mid, c["cyan"])

    list_h = box_h - chrome_h
    # 滚动 cursor 进可视范围
    # 让选中项尽量在中间
    visible_start = max(0, picker.cursor - list_h // 2)
    visible_start = min(visible_start, max(0, n_items - list_h))

    for i in range(list_h):
        y = y0 + 4 + i
        idx_in_list = visible_start + i
        if idx_in_list >= n_items:
            _safe_addstr(win, y, x0, blank, c["cyan"])
            continue
        opt_idx, label, total = items[idx_in_list]
        marker = "▶" if idx_in_list == picker.cursor else " "
        token_str = fmt_num(total) if total else ""
        # 内容宽度：box_w - 4 (左右边框+边距)
        content_w = box_w - 4
        token_w = len(token_str) + 1
        label_w = content_w - token_w - 2
        if len(label) > label_w:
            label_show = label[:label_w - 1] + "…"
        else:
            label_show = label
        line = f"│ {marker} {label_show:<{label_w}} {token_str:>{token_w}} │"
        attr = (c["reverse"] | curses.A_BOLD) if idx_in_list == picker.cursor else 0
        _safe_addstr(win, y, x0, line, attr)

    _safe_addstr(win, y0 + box_h - 3, x0, mid, c["cyan"])
    hint_text = "│ ↑↓ 选择  Enter 应用  Esc 取消  打字过滤  Ctrl-U 清空"
    _safe_addstr(win, y0 + box_h - 2, x0, hint_text.ljust(box_w - 1)[:box_w - 1] + "│", c["dim"])
    _safe_addstr(win, y0 + box_h - 1, x0, bot, c["cyan"])


def _draw(win, state: TuiState, c: Dict[str, int]) -> None:
    win.erase()
    h, w = win.getmaxyx()

    # 标题行
    title_left = "aix · AI token 用量"
    filt = []
    tool_show = TOOL_LABEL.get(state.tool_filter, "全部") if state.tool_filter else "全部数据源"
    filt.append(f"源={tool_show}")
    if state.project_filter:
        filt.append(f"项目={state.project_filter}")
    if state.model_filter:
        filt.append(f"模型={state.model_filter}")
    title_right = "  ".join(filt)
    _safe_addstr(win, 0, 0, title_left, curses.A_BOLD | c["cyan"])
    _safe_addstr(win, 0, max(0, w - len(title_right) - 1), title_right, c["dim"])

    # 维度 / 范围切换条
    _draw_tabs(win, 2, "维度", DIMS, state.dim_idx, c)
    _draw_tabs(win, 3, "范围", RANGES, state.range_idx, c)

    # 数据表
    buckets, grand = _compute_table(state)
    h_avail = h - 5 - 5
    max_scroll = max(0, len(buckets) - max(1, h_avail))
    if state.scroll > max_scroll:
        state.scroll = max_scroll
    if state.scroll < 0:
        state.scroll = 0

    _draw_table(win, 5, buckets, grand, state, c)
    _draw_footer(win, state, c)

    if state.picker:
        _draw_picker(win, state.picker, c)
    win.refresh()


def _build_picker(state: TuiState, field: str) -> Picker:
    """field ∈ {project, model, tool}。从原始 rows 聚合一份选项列表。"""
    if field == "tool":
        opts: Dict[str, int] = defaultdict(int)
        for r in state.rows:
            opts[r.tool] += r.total
        items = [("(全部)", 0)] + [
            (TOOL_LABEL.get(t, t), opts[t]) for t in sorted(opts, key=lambda k: -opts[k])
        ]
        title = "选择数据源"
    elif field == "model":
        opts = defaultdict(int)
        for r in state.rows:
            if state.tool_filter and r.tool != state.tool_filter:
                continue
            opts[r.model] += r.total
        items = [("(全部)", 0)] + [(m, opts[m]) for m in sorted(opts, key=lambda k: -opts[k])]
        title = "选择模型"
    else:  # project
        opts = defaultdict(int)
        for r in state.rows:
            if state.tool_filter and r.tool != state.tool_filter:
                continue
            opts[r.project] += r.total
        items = [("(全部)", 0)] + [
            (short_project(p, 60), opts[p]) for p in sorted(opts, key=lambda k: -opts[k])
        ]
        title = "选择项目"
    return Picker(title=title, field=field, options=items, cursor=0, query="")


def _apply_picker(state: TuiState) -> None:
    """根据当前 picker.cursor 套用选择。"""
    p = state.picker
    if not p:
        return
    items = p.filtered()
    if not items:
        state.picker = None
        return
    _, label, _ = items[p.cursor]
    if p.field == "tool":
        if label == "(全部)":
            state.tool_filter = ""
        else:
            # 反查 tool key
            for k, v in TOOL_LABEL.items():
                if v == label:
                    state.tool_filter = k
                    break
    elif p.field == "model":
        state.model_filter = "" if label == "(全部)" else label
    elif p.field == "project":
        # 用完整 cwd 反查不便；这里直接保存显示串作子串匹配（去掉 ~）
        if label == "(全部)":
            state.project_filter = ""
        else:
            # 去掉前导 "~" / "…"
            seed = label.lstrip("~").lstrip("…").lstrip("/")
            # 取尾部一段更稳：如 "Downloads/tools" 子串匹配最准
            parts = seed.split("/")
            state.project_filter = parts[-1] if parts else seed
    state.picker = None
    state.scroll = 0


def _handle_picker_key(state: TuiState, ch: int) -> None:
    p = state.picker
    if not p:
        return
    items = p.filtered()
    n = len(items)
    if ch == 27:  # Esc
        state.picker = None
        return
    if ch in (10, 13):  # Enter
        _apply_picker(state)
        return
    if ch in (curses.KEY_DOWN,) and n:
        p.cursor = (p.cursor + 1) % n
        return
    if ch in (curses.KEY_UP,) and n:
        p.cursor = (p.cursor - 1) % n
        return
    if ch == curses.KEY_NPAGE and n:
        p.cursor = min(n - 1, p.cursor + 10)
        return
    if ch == curses.KEY_PPAGE and n:
        p.cursor = max(0, p.cursor - 10)
        return
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        p.query = p.query[:-1]
        p.cursor = 0
        return
    if ch == 21:  # Ctrl-U: 清空 query
        p.query = ""
        p.cursor = 0
        return
    if 32 <= ch < 127:
        p.query += chr(ch)
        p.cursor = 0


def _tui_main(stdscr, initial_rows: List[Row], initial_tools: List[str]) -> None:
    curses.curs_set(0)
    stdscr.timeout(-1)
    c = _init_curses_colors()

    state = TuiState(rows=initial_rows)
    # 启动时如果只有一个 tool，预设为筛选项
    if len(initial_tools) == 1:
        state.tool_filter = initial_tools[0]

    while True:
        _draw(stdscr, state, c)
        ch = stdscr.getch()

        if state.picker:
            _handle_picker_key(state, ch)
            state.status = ""
            continue

        state.status = ""

        if ch in (ord("q"), 27):
            return
        elif ch in (curses.KEY_LEFT, ord("h")):
            state.range_idx = (state.range_idx - 1) % len(RANGES)
            state.scroll = 0
        elif ch in (curses.KEY_RIGHT, ord("l")):
            state.range_idx = (state.range_idx + 1) % len(RANGES)
            state.scroll = 0
        elif ch in (curses.KEY_DOWN, ord("j")):
            state.scroll += 1
        elif ch in (curses.KEY_UP, ord("k")):
            state.scroll -= 1
        elif ch == curses.KEY_NPAGE:
            state.scroll += 10
        elif ch == curses.KEY_PPAGE:
            state.scroll -= 10
        elif ch == ord("\t"):
            state.dim_idx = (state.dim_idx + 1) % len(DIMS)
            state.scroll = 0
        elif ord("1") <= ch <= ord("5"):
            state.dim_idx = min(ch - ord("1"), len(DIMS) - 1)
            state.scroll = 0
        elif ch in (ord("p"), ord("/")):
            state.picker = _build_picker(state, "project")
        elif ch == ord("m"):
            state.picker = _build_picker(state, "model")
        elif ch == ord("t"):
            state.picker = _build_picker(state, "tool")
        elif ch == ord("c"):
            state.tool_filter = ""
            state.project_filter = ""
            state.model_filter = ""
            state.scroll = 0
        elif ch == ord("s"):
            state.sort = "label" if state.sort == "total" else "total"
        elif ch == ord("r"):
            state.status = "重新扫描中…"
            _draw(stdscr, state, c)
            state.rows = collect_rows()
            state.status = "已重扫"
        elif ch == ord("?"):
            state.status = (
                "p项目  m模型  t数据源（弹窗选择，打字过滤；Enter确认/Esc取消） · "
                "1-5切维度 · ←→切范围 · ↑↓滚动 · c清空过滤 · s排序 · r重扫 · q退出"
            )


def run_tui(tools: List[str]) -> int:
    sys.stderr.write("加载中…\n")
    sys.stderr.flush()
    rows = collect_rows(tools=tools)
    if not rows:
        print("没有发现 AI 日志（~/.claude/projects/ 和 ~/.codex/sessions/ 都没数据）", file=sys.stderr)
        return 1
    try:
        curses.wrapper(_tui_main, rows, tools)
    finally:
        # 终端已由 wrapper 恢复；跳过 Python 关闭时对几十万对象的 GC，秒退
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="aix",
        description="Claude Code token 用量统计（读 ~/.claude/projects/）",
    )
    parser.add_argument(
        "-b", "--by",
        choices=["day", "model", "project", "session", "tool"],
        default="day",
        help="聚合维度（默认 day）",
    )
    parser.add_argument(
        "-T", "--tool",
        choices=["claude", "codex", "all"],
        default="all",
        help="数据源（默认 all：Claude Code + Codex）",
    )
    parser.add_argument("-s", "--since", default="7d", help="时间范围：7d / 30d / 2026-01-01 / all（默认 7d）")
    parser.add_argument("-n", "--top", type=int, default=20, help="最多显示行数（默认 20，0=全部）")
    parser.add_argument("--sort", choices=["total", "label"], default="total", help="排序方式（默认 total 降序）")
    parser.add_argument("-p", "--project", help="过滤项目（子串匹配）")
    parser.add_argument("-m", "--model", help="过滤模型（子串匹配）")
    parser.add_argument("--watch", type=float, nargs="?", const=5.0, help="持续刷新（秒，默认 5）")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示缓存命中信息")
    parser.add_argument("--no-cache", action="store_true", help="忽略缓存全量重解析")
    parser.add_argument("-i", "--interactive", action="store_true", help="进入交互式 TUI（curses）")
    args = parser.parse_args()

    tools = TOOLS_ALL if args.tool == "all" else [args.tool]

    if args.interactive:
        return run_tui(tools)

    since = parse_since(args.since)

    if args.no_cache and CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
        except OSError:
            pass

    def render_once() -> None:
        rows = collect_rows(tools=tools, verbose=args.verbose)
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
