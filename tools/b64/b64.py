#!/usr/bin/env python3
"""b64 - base64 双向自动识别。

默认自动判断方向：输入像 base64 → 解码；否则 → 编码。
也支持显式 -e/-d、url-safe、文件 IO、剪贴板进出。
结果默认同时打到 stdout 和剪贴板（与 json 工具一致）。
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import subprocess
import sys
from typing import Optional, Tuple

_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("B64_FORCE_COLOR") or sys.stdout.isatty())
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


# 常见文件 magic
MAGIC_BYTES = [
    (b"\x89PNG\r\n\x1a\n", "PNG 图像"),
    (b"\xff\xd8\xff",      "JPEG 图像"),
    (b"GIF87a",            "GIF 图像"),
    (b"GIF89a",            "GIF 图像"),
    (b"%PDF-",             "PDF 文档"),
    (b"PK\x03\x04",        "ZIP / docx / xlsx 等"),
    (b"\x1f\x8b\x08",      "Gzip"),
    (b"BZh",               "Bzip2"),
    (b"\x7fELF",           "ELF 可执行文件"),
    (b"\xcf\xfa\xed\xfe",  "Mach-O 64 可执行文件"),
    (b"\xfe\xed\xfa\xce",  "Mach-O 32 可执行文件"),
    (b"\xca\xfe\xba\xbe",  "Java class / Mach-O fat"),
    (b"MZ",                "Windows EXE"),
    (b"{",                 "可能是 JSON"),
    (b"[",                 "可能是 JSON"),
    (b"<",                 "可能是 XML / HTML"),
]


def detect_kind(b: bytes) -> Optional[str]:
    for sig, name in MAGIC_BYTES:
        if b.startswith(sig):
            return name
    return None


def is_base64ish(s: str) -> bool:
    """快速判断字符串是否像 base64（标准或 url-safe）。"""
    cleaned = re.sub(r"\s", "", s)
    if len(cleaned) < 4:
        return False
    # 标准字符集 + url-safe 字符集
    if not re.fullmatch(r"[A-Za-z0-9+/=_\-]+", cleaned):
        return False
    # 长度合法（mod 4 in {0, 2, 3}）
    body = cleaned.rstrip("=")
    if len(body) % 4 == 1:
        return False
    return True


def try_decode(s: str) -> Optional[bytes]:
    """尝试解码标准 + url-safe，自动补齐 padding。"""
    cleaned = re.sub(r"\s", "", s)
    if not cleaned:
        return None
    body = cleaned.rstrip("=")
    pad = (-len(body)) % 4
    candidates = [body + "=" * pad]
    # 同时尝试原始填充
    if cleaned not in candidates:
        candidates.insert(0, cleaned)
    for c in candidates:
        # 标准
        try:
            return base64.b64decode(c, validate=True)
        except (binascii.Error, ValueError):
            pass
        # url-safe
        try:
            return base64.urlsafe_b64decode(c)
        except (binascii.Error, ValueError):
            pass
    return None


def looks_like_text(b: bytes) -> Tuple[bool, Optional[str]]:
    """判断字节是否像文本，返回 (是否, 解码后的字符串或 None)。"""
    if not b:
        return False, None
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return False, None
    printable = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    if len(s) == 0:
        return False, None
    return printable / len(s) >= 0.85, s


def auto_direction(raw_text: str) -> str:
    """返回 'decode' 或 'encode'。"""
    if not is_base64ish(raw_text):
        return "encode"
    decoded = try_decode(raw_text)
    if decoded is None:
        return "encode"
    is_text, _ = looks_like_text(decoded)
    if is_text:
        return "decode"
    # 二进制但 magic 命中也算 decode
    if detect_kind(decoded):
        return "decode"
    # 全是字母数字的短字符串（可能就是普通词，比如 'hello'）：encode
    if re.fullmatch(r"[A-Za-z0-9]+", raw_text.strip()) and len(raw_text.strip()) < 16:
        return "encode"
    # 其他情况倾向解码
    return "decode"


def encode(b: bytes, url_safe: bool) -> str:
    if url_safe:
        return base64.urlsafe_b64encode(b).decode("ascii")
    return base64.b64encode(b).decode("ascii")


def hex_dump(b: bytes, max_bytes: int = 32) -> str:
    chunk = b[:max_bytes]
    hex_part = " ".join(f"{x:02X}" for x in chunk)
    ascii_part = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
    suffix = f" ... ({len(b) - max_bytes} bytes more)" if len(b) > max_bytes else ""
    return f"{hex_part}\n  {DIM}ASCII: {ascii_part}{suffix}{RESET}"


def copy_to_clipboard(text: str) -> bool:
    try:
        proc = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def read_clipboard() -> str:
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, check=True)
        return result.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"✗ 读取剪贴板失败: {e}")


def render_decode(input_text: str, output: bytes, used_charset: str) -> None:
    is_text, text_form = looks_like_text(output)
    kind = detect_kind(output)

    head = f"{DIM}输入:{RESET} {_truncate(input_text.strip(), 60)}  {DIM}→{RESET}  {YELLOW}Base64 解码{RESET}"
    print(head)
    print()

    rows = []
    if is_text and text_form is not None:
        # 文本：直接展示
        display = text_form if len(text_form) <= 500 else text_form[:500] + f"\n{DIM}... 截断（共 {len(text_form)} 字符，完整内容已入剪贴板）{RESET}"
        rows.append(("结果",  f"{GREEN}{display}{RESET}"))
        rows.append(("长度",  f"{len(input_text.strip())} 字符 (base64) → {len(output)} 字节 (解码)"))
        rows.append(("字符集", "UTF-8"))
    else:
        # 二进制
        kind_str = f"{YELLOW}{kind}{RESET}" if kind else f"{DIM}未知二进制{RESET}"
        rows.append(("类型",  kind_str))
        rows.append(("长度",  f"{len(input_text.strip())} 字符 (base64) → {len(output)} 字节 (解码)"))
        rows.append(("Hex",   hex_dump(output)))
    if "_" in input_text or "-" in input_text:
        rows.append(("变体", "url-safe"))

    label_w = max(len(k) for k, _ in rows)
    for k, v in rows:
        # multiline 值要 indent
        lines = str(v).split("\n")
        print(f"  {CYAN}{k.ljust(label_w)}{RESET}  {lines[0]}")
        for ln in lines[1:]:
            print(f"  {' ' * label_w}  {ln}")


def render_encode(input_bytes: bytes, output: str, url_safe: bool) -> None:
    head = f"{DIM}输入:{RESET} {_truncate(_safe_preview(input_bytes), 60)}  {DIM}→{RESET}  {YELLOW}Base64 编码{RESET}"
    print(head)
    print()

    rows = [
        ("结果",   f"{GREEN}{output}{RESET}"),
        ("长度",   f"{len(input_bytes)} 字节 (原始) → {len(output)} 字符 (base64)"),
    ]
    if url_safe:
        rows.append(("变体", "url-safe"))

    label_w = max(len(k) for k, _ in rows)
    for k, v in rows:
        lines = str(v).split("\n")
        print(f"  {CYAN}{k.ljust(label_w)}{RESET}  {lines[0]}")
        for ln in lines[1:]:
            print(f"  {' ' * label_w}  {ln}")


def _safe_preview(b: bytes, max_chars: int = 60) -> str:
    try:
        s = b.decode("utf-8")
        return s
    except UnicodeDecodeError:
        return f"<二进制 {len(b)} bytes>"


def _truncate(s: str, w: int) -> str:
    s = s.replace("\n", "\\n").replace("\r", "\\r")
    if len(s) <= w:
        return s
    return s[: w - 1] + "…"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="b64",
        description="base64 双向自动识别（默认自动判断方向）",
    )
    p.add_argument("input", nargs="*", help="要处理的字符串；不传则读 stdin / -c 剪贴板 / -i 文件")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-e", "--encode", action="store_true", help="强制编码")
    g.add_argument("-d", "--decode", action="store_true", help="强制解码")
    p.add_argument("-u", "--url", action="store_true",
                   help="编码时输出 url-safe 变体（解码时自动识别）")
    p.add_argument("-c", "--clip", action="store_true", help="从剪贴板读输入")
    p.add_argument("-i", "--input-file", help="从文件读输入（编码时按二进制读）")
    p.add_argument("-o", "--output-file", help="写入文件（解码二进制时推荐）")
    p.add_argument("--no-clip", action="store_true", help="不复制结果到剪贴板")
    p.add_argument("-r", "--raw", action="store_true",
                   help="只输出结果，不带任何修饰（脚本/管道用）")
    return p


def main(argv) -> int:
    args = build_parser().parse_args(argv)

    # 决定输入来源
    raw_bytes: Optional[bytes] = None
    raw_text: Optional[str] = None

    if args.input_file:
        try:
            with open(args.input_file, "rb") as f:
                raw_bytes = f.read()
        except OSError as e:
            print(f"✗ 读取文件失败: {e}", file=sys.stderr)
            return 1
        # 文件输入默认编码方向（除非显式 -d）
        if not args.decode and not args.encode:
            args.encode = True
    elif args.clip:
        raw_text = read_clipboard().strip()
    elif args.input:
        raw_text = " ".join(args.input)
    elif not sys.stdin.isatty():
        raw_text = sys.stdin.read().strip()
    else:
        print("✗ 没有输入。给一个字符串、用 -c 读剪贴板、-i 读文件、或从管道传入",
              file=sys.stderr)
        return 1

    # 决定方向
    if args.encode:
        direction = "encode"
    elif args.decode:
        direction = "decode"
    else:
        if raw_text is not None:
            direction = auto_direction(raw_text)
        else:
            direction = "encode"  # 文件输入 fallback

    # 执行
    if direction == "decode":
        if raw_text is None:
            print("✗ 解码需要文本输入", file=sys.stderr)
            return 1
        decoded = try_decode(raw_text)
        if decoded is None:
            print(f"{RED}✗ 输入不是合法的 base64{RESET}", file=sys.stderr)
            print(f"{DIM}  提示：用 -e 强制编码{RESET}", file=sys.stderr)
            return 1
        # 输出
        if args.output_file:
            try:
                with open(args.output_file, "wb") as f:
                    f.write(decoded)
                if not args.raw:
                    print(f"{GREEN}✓{RESET} {len(decoded)} 字节已写入 {args.output_file}")
                return 0
            except OSError as e:
                print(f"✗ 写文件失败: {e}", file=sys.stderr)
                return 1

        is_text, text_form = looks_like_text(decoded)
        if args.raw:
            if is_text:
                sys.stdout.write(text_form)
            else:
                # raw 模式下二进制直接写到 stdout
                sys.stdout.buffer.write(decoded)
            return 0

        render_decode(raw_text, decoded, "url-safe" if "_" in raw_text or "-" in raw_text else "标准")

        # 剪贴板：仅当结果是文本
        if not args.no_clip:
            if is_text:
                if copy_to_clipboard(text_form):
                    print(f"\n{GREEN}✓{RESET} {DIM}已复制到剪贴板{RESET}")
                else:
                    print(f"\n{YELLOW}⚠ 未能复制到剪贴板（pbcopy 不可用）{RESET}")
            else:
                print(f"\n{YELLOW}⚠ 二进制结果未复制到剪贴板，建议用 -o 写入文件{RESET}")
        return 0

    # encode
    if raw_bytes is None:
        assert raw_text is not None
        raw_bytes = raw_text.encode("utf-8")
    encoded = encode(raw_bytes, url_safe=args.url)

    if args.raw:
        sys.stdout.write(encoded)
        return 0

    render_encode(raw_bytes, encoded, url_safe=args.url)

    if not args.no_clip:
        if copy_to_clipboard(encoded):
            print(f"\n{GREEN}✓{RESET} {DIM}已复制到剪贴板{RESET}")
        else:
            print(f"\n{YELLOW}⚠ 未能复制到剪贴板（pbcopy 不可用）{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
