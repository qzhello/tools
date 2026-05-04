# ports

列出本机所有监听端口（TCP + UDP），显示协议、地址、进程、PID、用户，自动识别常见服务。

## 用法

```bash
ports                    # 全部监听端口
ports 3306               # 只看 3306（按端口过滤）
ports node               # 按进程名/服务名过滤
ports --tcp              # 仅 TCP
ports --udp              # 仅 UDP
ports -k 3000            # 杀掉占 3000 的进程（二次确认 → SIGTERM → 必要时 SIGKILL）
ports -k node -y         # 跳过所有确认（危险）
ports -j                 # JSON 输出（脚本用）
```

## 输出

```
端口   协议  监听地址    服务         进程       PID    用户
─────  ────  ──────────  ───────────  ─────────  ─────  ────────
3000   TCP   *           node-dev     node       12345  quzhihao
3306   TCP   127.0.0.1   mysql        mysqld     234    _mysql
5173   TCP   ::1         vite         node       456    quzhihao
8080   TCP   *           http-alt     nginx      789    _www
53     UDP   *           dns          mDNSResp   100    _mdns
```

颜色：
- `*` 监听任意地址 → 黄色（外部可访问）
- `127.x.x.x` / `::1` 仅本机 → 绿色
- 已知服务名 → 绿色；未知 → `-` 灰色

## -k 杀进程流程

1. 显示要杀的进程列表
2. 等用户确认 `[y/N]`
3. 全部 `SIGTERM`
4. 等 2 秒
5. 仍存活的进程 → 询问是否 `SIGKILL`
6. 杀不动（如系统进程）会提示需要 `sudo`

`-y` 跳过所有确认。

## 退出码

- `0`：正常
- `1`：参数错误，或 `-k` 没有匹配项

## 依赖

- `python3`（macOS 自带）
- `lsof`（macOS / Linux 自带）

## License

MIT
