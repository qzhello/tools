# pingx

实时可视化 ping。包装系统 `ping`，加上 sparkline 折线、丢包率、延迟分位数。排查网络抖动比裸 `ping` 直观得多。

## 用法

```bash
pingx baidu.com                # 默认 1 秒一次，无限循环
pingx 8.8.8.8 -c 20            # 发 20 个包后退出
pingx baidu.com -i 0.5         # 0.5 秒一次（macOS 子秒级需 sudo）
pingx baidu.com -w 120         # sparkline 窗口扩到 120 个采样
```

`Ctrl-C` 退出后会打印汇总（含 p50/p95/p99）。

## 输出

```
pingx baidu.com  (Ctrl-C 退出)

  目标    baidu.com → 220.181.38.149
  已发送  42    丢包  1 (2.4%)    用时 42s
  当前    23.4 ms
  最近    ▂▃▂▄▃▂▁▂▃✗▂▃▄▃▂  最近 15/60
  延迟    min 18.2  avg 24.5  p95 31.2  max 45.1 ms
```

颜色规则（终端有 TTY 时）：

| 延迟    | 颜色 | 含义 |
|---------|------|------|
| < 50 ms | 绿色 | 健康 |
| < 150 ms| 黄色 | 一般 |
| ≥ 150 ms| 红色 | 慢   |
| 超时    | 灰色 ✗ | 丢包 |

丢包率：0% 绿，<5% 黄，≥5% 红。设 `NO_COLOR=1` 关闭颜色。

## 选项

| 选项 | 说明 | 默认 |
|------|------|------|
| `-i, --interval N` | 发送间隔（秒）         | 1.0 |
| `-c, --count N`    | 发 N 个包后退出（0=无限） | 0 |
| `-w, --window N`   | sparkline 窗口大小      | 60 |

## 退出码

- `0`：正常结束（至少收到一个回包）
- `1`：发送了但完全没收到回包，或参数错误
- `130`：被 Ctrl-C 中断（Python 默认）

## 依赖

- `python3`（macOS 自带）
- `ping`（macOS / Linux 自带）

## License

MIT
