#!/usr/bin/env python3
"""给已美化的 JSON 文本加 ANSI 颜色，便于终端阅读。

读 stdin，写 stdout。不重新解析 JSON，仅按词法着色（输入是
json.dumps 的输出，结构稳定）。
"""

import sys
import re

RESET = "\x1b[0m"
COLOR = {
    "key":  "\x1b[1;36m",  # bold cyan
    "str":  "\x1b[32m",    # green
    "num":  "\x1b[33m",    # yellow
    "bool": "\x1b[1;31m",  # bold red
    "null": "\x1b[1;31m",  # bold red
}

TOKEN_RE = re.compile(
    r'(?P<key>"(?:[^"\\]|\\.)*"(?=\s*:))'
    r'|(?P<str>"(?:[^"\\]|\\.)*")'
    r'|(?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|(?P<bool>\btrue\b|\bfalse\b)'
    r'|(?P<null>\bnull\b)'
)


def paint(match: "re.Match[str]") -> str:
    kind = match.lastgroup or ""
    return f"{COLOR[kind]}{match.group(0)}{RESET}" if kind in COLOR else match.group(0)


def main() -> int:
    sys.stdout.write(TOKEN_RE.sub(paint, sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
