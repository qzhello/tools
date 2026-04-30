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

# ANSI（仅当 stderr 是 TTY 时）
_USE_COLOR = sys.stderr.isatty()
RED = "\x1b[1;31m" if _USE_COLOR else ""
DIM = "\x1b[2m" if _USE_COLOR else ""
RESET = "\x1b[0m" if _USE_COLOR else ""


def _highlight_error(text: str, exc: json.JSONDecodeError) -> str:
    """渲染带行号/箭头的错误上下文。"""
    lines = text.splitlines() or [""]
    lineno = max(1, min(exc.lineno, len(lines)))
    colno = max(1, exc.colno)

    # 显示窗口：错误行前后各 2 行
    start = max(1, lineno - 2)
    end = min(len(lines), lineno + 2)
    width = len(str(end))

    out = []
    out.append(f"✗ JSON 解析失败: {exc.msg}（行 {exc.lineno}，列 {exc.colno}）")
    for i in range(start, end + 1):
        marker = f"{RED}>{RESET}" if i == lineno else " "
        out.append(f"  {marker} {i:>{width}} | {lines[i-1]}")
        if i == lineno:
            pad = " " * (4 + width + 3 + (colno - 1))
            out.append(f"{pad}{RED}^{RESET} {DIM}here{RESET}")
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
