# json

JSON 美化小工具，一条命令把压缩 / 凌乱的 JSON 格式化并复制到剪贴板。

## 用法

```bash
json '{"a":1,"b":[2,3]}'        # 参数（务必单引号包住，避免 shell 转义）
echo '{"a":1}' | json           # 管道
curl -s api.example.com | json  # 任何 stdout 都能直接喂
json                            # 无参：从剪贴板读取
```

输出：美化后的 JSON 同时打到 **stdout** 与 **剪贴板**。终端显示带语法高亮（key=青、字符串=绿、数字=黄、布尔/null=红），管道或剪贴板自动去掉颜色。设 `NO_COLOR=1` 可强制关闭颜色。

## 宽容解析

很多时候你拿到的不是合法 JSON —— 带 `//` 注释、尾随逗号、来自 JS 控制台的对象字面量、Python 字典 `repr` 输出等等。本工具按以下顺序尝试，并标注用了哪种模式：

| 顺序 | 模式 | 处理 |
|---|---|---|
| 1 | `strict` | 严格 JSON |
| 2 | `lenient` | 去掉 `//` `/* */` 注释和尾随逗号后再解析 |
| 3 | `pyobj` | 当作 Python dict / JS 对象字面量解析（支持单引号、`True`/`False`/`None`） |
| 4 | `raw` | 全部失败 → 原样写入剪贴板，并提示原始 JSON 错误 |

例：

```bash
$ json '{"a":1, /* hi */ "b":[1,2,], }'
{
  "a": 1,
  "b": [
    1,
    2
  ]
}
⚠ 输入含注释或尾随逗号，已宽容解析后美化（来源: 参数）
✓ 已复制到剪贴板

$ json "{'a': 1, 'b': True, 'c': None}"
{
  "a": 1,
  "b": true,
  "c": null
}
⚠ 输入不是合法 JSON，按 Python/JS 对象字面量解析（来源: 参数）
✓ 已复制到剪贴板
```

## 依赖

- macOS 自带的 `pbcopy` / `pbpaste` / `python3`
- 无第三方依赖

## 注意事项

- JSON 含 `"`、`$`、`!` 等字符时，参数模式**一定要单引号包住**：`json '...'`，否则会被 shell 拆碎。
- 中文原样保留，不会被转义成 `\uXXXX`。
- 仅支持 macOS。Linux 用户可自行替换为 `xclip` / `wl-copy`。

## License

MIT
