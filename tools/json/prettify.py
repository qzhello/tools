#!/usr/bin/env python3
"""json 工具的宽容美化器。

stdin: 待美化的输入文本
stdout: 美化结果（解析失败时原样输出）
stderr: 单行 mode=<strict|lenient|pyobj|raw>，raw 模式下追加 err=<原始错误>
exit:  0 成功，1 输入为空，2 全部解析失败
"""

import sys
import json
import ast
import re


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
    except Exception as exc:
        first_err = str(exc)

    # 2) 去掉 // /* */ 注释和尾随逗号
    try:
        cleaned = re.sub(r"//[^\n]*", "", raw)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
        cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
        emit(json.loads(cleaned), "lenient")
        return 0
    except Exception:
        pass

    # 3) Python / JS 对象字面量（单引号、True/False/None）
    try:
        emit(ast.literal_eval(raw), "pyobj")
        return 0
    except Exception:
        pass

    # 4) 全部失败：原样输出
    sys.stdout.write(raw)
    print("mode=raw", file=sys.stderr)
    print(f"err={first_err}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
