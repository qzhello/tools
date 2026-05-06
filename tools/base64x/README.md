# b64

base64 双向转换。**默认自动判断方向**：输入像 base64 → 解码；否则 → 编码。结果同时打到 stdout 和剪贴板。

JWT、URL 参数、配置文件里看到一串疑似 base64 时，最快验证方式。

## 用法

```bash
b64 "Hello, 世界"                 # 自动 → 编码
b64 SGVsbG8sIOS4lueVjA==          # 自动 → 解码
b64 -e "subjects?abc=1" -u        # 强制编码 + url-safe
b64 -d eyJhbGciOiJIUzI1Nn0        # 强制解码（少 padding 也认）
b64 -c                            # 从剪贴板读
echo "hello" | b64                # 从管道读
b64 -i photo.png                  # 编码二进制文件
b64 -d -o out.png "iVBORw0KGgo..." # 解码并写入文件
b64 "test" -r                     # raw 模式：仅输出结果，无修饰（脚本/管道用）
b64 "test" --no-clip              # 不写剪贴板
```

## 自动方向

判断输入字符串：

1. 字符全在 `[A-Za-z0-9+/=_-]`、长度 ≥ 4、且 `mod 4` 合法 → **尝试解码**
2. 解码结果是 UTF-8 文本（≥ 85% 可打印） → 解码
3. 解码结果有已知文件 magic（PNG/JPEG/PDF/Gzip/...） → 解码
4. 否则 → **编码**

特殊兜底：纯字母数字短词（如 `hello`）即使长度合法也判为编码。歧义场景下用 `-e` / `-d` 显式指定。

## url-safe

- 编码：`-u` 输出 `_` `-` 替代 `/` `+`
- 解码：自动识别（无需指定）

## 输出

```
b64 SGVsbG8sIOS4lueVjA==

输入: SGVsbG8sIOS4lueVjA==  →  Base64 解码

  结果   Hello, 世界
  字节数  20 → 13 字节
  字符集  UTF-8

✓ 已复制到剪贴板
```

二进制结果：

```
b64 iVBORw0KGgoAAAANSUhEUg...

输入: iVBORw0KGgo...  →  Base64 解码

  类型   PNG 图像
  字节数  39 → 29 字节
  Hex    89 50 4E 47 0D 0A 1A 0A 00 00 00 0D 49 48 44 52 ...
         ASCII: .PNG........IHDR.............

⚠ 二进制结果未复制到剪贴板，建议用 -o 写入文件
```

## 选项

| 选项 | 说明 |
|------|------|
| `-e, --encode`        | 强制编码 |
| `-d, --decode`        | 强制解码 |
| `-u, --url`           | 编码用 url-safe（解码自动识别） |
| `-c, --clip`          | 从剪贴板读输入 |
| `-i, --input-file F`  | 从文件读（默认编码方向） |
| `-o, --output-file F` | 写入文件（解码二进制时推荐） |
| `--no-clip`           | 不写剪贴板 |
| `-r, --raw`           | 只输出结果裸字符串（脚本/管道用） |

## 退出码

- `0`：成功
- `1`：解码失败（输入非合法 base64）/ 文件错误 / 没有输入

## 依赖

- `python3`（macOS 自带）
- `pbcopy` / `pbpaste`（仅剪贴板模式需要，macOS 自带）

## License

MIT
