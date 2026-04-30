#!/usr/bin/env python3
"""json 工具的宽容美化器。

stdin: 待美化的输入文本
stdout: 美化结果（解析失败时原样输出）
stderr: 第 1 行 mode=<strict|lenient|pyobj|raw>，raw 模式下追加高亮的错误上下文
exit:  0 成功，1 输入为空，2 全部解析失败
"""

import sys
import json
import ast
import re

# ANSI 决策：
#   1. NO_COLOR 设置 → 关
#   2. JSON_FORCE_COLOR 设置 → 开
#   3. 否则看 stderr 是否 TTY
import os
_USE_COLOR = (
    not os.environ.get("NO_COLOR")
    and (os.environ.get("JSON_FORCE_COLOR") or sys.stderr.isatty())
)
RED = "\x1b[1;31m" if _USE_COLOR else ""
DIM = "\x1b[2m" if _USE_COLOR else ""
RESET = "\x1b[0m" if _USE_COLOR else ""


def _bad_token_span(line: str, col: int) -> tuple:
    """返回错误位置的 (start, end) 字符索引（半开区间，0-based）。

    word/数字字符向两侧扩展，标点/空白只标 1 个字符。
    """
    idx = max(0, min(col - 1, len(line) - 1)) if line else 0
    if not line:
        return (0, 1)
    ch = line[idx]
    is_word = lambda c: c.isalnum() or c == "_"
    if is_word(ch):
        s = idx
        while s > 0 and is_word(line[s - 1]):
            s -= 1
        e = idx
        while e < len(line) and is_word(line[e]):
            e += 1
        return (s, e)
    return (idx, idx + 1)


def _paint_line(line: str, start: int, end: int) -> str:
    """把 line[start:end] 用红色反白显示。"""
    if not _USE_COLOR:
        return line
    return f"{line[:start]}{RED}{line[start:end]}{RESET}{line[end:]}"


def _highlight_error(text: str, exc: json.JSONDecodeError) -> str:
    """渲染带行号/箭头的错误上下文，错误 token 在源码行里也染红。"""
    lines = text.splitlines() or [""]
    lineno = max(1, min(exc.lineno, len(lines)))
    colno = max(1, exc.colno)

    # 显示窗口：错误行前后各 2 行
    start_ln = max(1, lineno - 2)
    end_ln = min(len(lines), lineno + 2)
    width = len(str(end_ln))

    bad_line = lines[lineno - 1]
    tok_s, tok_e = _bad_token_span(bad_line, colno)
    tok_len = max(1, tok_e - tok_s)

    out = [f"✗ JSON 解析失败: {exc.msg}（行 {exc.lineno}，列 {exc.colno}）"]
    for i in range(start_ln, end_ln + 1):
        if i == lineno:
            marker = f"{RED}>{RESET}"
            shown = _paint_line(bad_line, tok_s, tok_e)
        else:
            marker = " "
            shown = lines[i - 1]
        out.append(f"  {marker} {i:>{width}} | {shown}")
        if i == lineno:
            pad = " " * (4 + width + 3 + tok_s)
            caret = "^" * tok_len
            out.append(f"{pad}{RED}{caret}{RESET} {DIM}here{RESET}")
    return "\n".join(out)


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 1

    def emit(obj: object, mode: str) -> None:
        out = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)
        sys.stdout.write(out)
        print(f"mode={mode}", file=sys.stderr)

    # 1) 严格 JSON
    try:
        emit(json.loads(raw), "strict")
        return 0
    except json.JSONDecodeError as exc:
        first_err = exc

    # 2) 去注释 + 去尾随逗号
    try:
        cleaned = re.sub(r"//[^\n]*", "", raw)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
        cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
        emit(json.loads(cleaned), "lenient")
        return 0
    except Exception:
        pass

    # 3) Python / JS 对象字面量
    try:
        emit(ast.literal_eval(raw), "pyobj")
        return 0
    except Exception:
        pass

    # 4) 全部失败：原样输出 + 高亮错误位置
    sys.stdout.write(raw)
    print("mode=raw", file=sys.stderr)
    print(_highlight_error(raw, first_err), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
