# dnsx

并行查询多个 DNS resolver，对比结果，**返回不一致时高亮**。排查 CDN 路由、DNS 污染、解析未生效时刚需。

## 用法

```bash
dnsx baidu.com                          # 默认 5 个 resolver × 6 种记录
dnsx github.com -t A,AAAA               # 仅指定记录类型
dnsx baidu.com --all-types              # 查所有支持的类型
dnsx example.com --only Google,阿里     # 仅用指定 resolver
dnsx example.com -r 9.9.9.9             # 添加额外 resolver
dnsx baidu.com --timeout 5              # 单次超时 5s（默认 3s）
dnsx baidu.com -j                       # JSON 输出
```

## 默认 resolver

| 名字       | 服务器             |
|------------|--------------------|
| 系统       | （读 /etc/resolv.conf） |
| Google     | 8.8.8.8           |
| Cloudflare | 1.1.1.1           |
| 114DNS     | 114.114.114.114   |
| 阿里       | 223.5.5.5         |

## 默认查询的记录类型

`A`, `AAAA`, `CNAME`, `NS`, `MX`, `TXT`

`--all-types` 会加上 `SOA`, `PTR`, `SRV`, `CAA`。

## 输出

```
dnsx baidu.com  via 5 resolvers

A       ⚠ 不一致
        220.181.38.149   [系统, Google, 114DNS, 阿里]
        220.181.38.150   [系统, Google, 114DNS, 阿里]
        220.181.38.151   [Cloudflare]

AAAA    （无记录）

NS      ✓ 一致
        dns.baidu.com    [全部]
        ns2.baidu.com    [全部]
```

- `✓ 一致`（绿）：所有 resolver 返回相同集合
- `⚠ 不一致`（黄）：有差异，列出每个值是哪些 resolver 返回的
- `✗ 全部超时`（红）：网络不通
- `（无记录）`（灰）：所有 resolver 都查到该类型为空

## 典型使用场景

- **改了域名解析**：跑一下，看是不是各 resolver 都生效了
- **怀疑 DNS 污染**：对比国内（114/阿里）和海外（Google/Cloudflare）
- **CDN 排查**：看 CDN 在哪个区域返回了哪个节点 IP
- **MX/SPF/DKIM 验证**：一次查全所有邮件相关记录

## 依赖

- `python3`（macOS 自带）
- `dig`（macOS 自带，Linux 需 `bind-utils` / `dnsutils` 包）

## License

MIT
