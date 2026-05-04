# procx

进程查看器。包装 `ps`，按 CPU/内存排序，颜色高亮，支持过滤、进程树、杀进程。比裸 `ps` / `top` 直观。

## 用法

```bash
procx                    # 默认按 CPU 排序，前 20 个
procx -m                 # 按内存排序
procx -n 50              # 前 50 个
procx node               # 按命令名 / 用户名过滤
procx 12345              # 按 PID 精确过滤
procx -t                 # 进程树视图
procx -k chrome          # 杀掉所有 chrome 进程（带二次确认）
procx -k 12345 -y        # 跳过确认（危险）
procx node -j            # JSON 输出
```

## 输出

```
procx  top 5 by CPU，共 1218 个进程

PID    USER       %CPU  %MEM   RSS    TIME    命令
─────  ─────────  ────  ────  ──────  ──────  ─────────────────────────────────────
35338  quzhihao   96.6   0.4  261.1M     1s   npm install @anthropic-ai/claude-code
410    _windowsv  43.4   0.4  256.8M  151d6h  /System/Library/.../SkyLight.framework
14088  quzhihao   41.3   0.0   19.6M   46d9h  node /path/to/server.js
90841  quzhihao   25.8   0.9  566.4M  112d8h  /Applications/iTerm.app/Contents/...
60250  quzhihao   15.3   1.0  631.9M    7d18h  claude --dangerously-skip-permissions
```

## 颜色规则

| 维度 | 阈值 | 颜色 |
|------|------|------|
| %CPU | ≥80 红，≥30 黄，≥1 绿，<1 灰 |
| %MEM | ≥50 红，≥20 黄，≥1 绿，<1 灰 |
| RSS  | ≥1G 红，≥256M 黄，≥10M 绿，<10M 灰 |
| TIME | ≥7d 青，≥1d 紫，≥1h 普通，<1h 灰 |

## 进程树（-t）

```
0.7%CPU   19.1M      1 /sbin/launchd
├─ 52.1%CPU  19.6M  14088 node /path/to/server.js
│  └─  0.0%CPU   7.2M  14089 helper
├─ 45.3%CPU 257.7M    410 /System/.../SkyLight.framework
├─ 11.0%CPU 559.5M  90841 /Applications/iTerm.app/...
│  └─  0.0%CPU   288K  90843 iTerm2 helper
│     ├─  0.0%CPU   3.4M  60683 login -fp quzhihao
│     │  └─  0.0%CPU   6.8M  60684 -zsh
│     └─  ...
```

子节点按 CPU（或 `-m` 时按内存）降序。`-n N` 控制总输出节点数。

## -k 杀进程

和 `ports -k` 行为一致：

1. 列出要杀的进程
2. 二次确认 `[y/N]`
3. SIGTERM 全部
4. 等 2 秒
5. 仍存活的进程 → 询问 SIGKILL

**安全限制**：`-k` 匹配超过 50 个进程时拒绝执行（避免误杀），需要 `-y` 强制。

## 退出码

- `0`：正常
- `1`：参数错误，或 `-k` 无匹配 / 匹配过多

## 依赖

- `python3`（macOS 自带）
- `ps`（macOS / Linux 自带）

## License

MIT
