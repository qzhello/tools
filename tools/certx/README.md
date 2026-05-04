# certx

HTTPS 证书检查。一行命令看清：到期天数（即将过期高亮）、SAN、证书链、TLS 版本、签发者。证书快过期或线上 SSL 报错时刚需。

## 用法

```bash
certx example.com                  # 默认 443
certx example.com:8443             # 自定义端口
certx https://example.com/path     # URL 也行（路径忽略）
certx 1.2.3.4 --sni example.com    # IP + 显式 SNI
certx example.com -j               # JSON 输出
certx example.com --timeout 15     # 链路慢时调大
```

## 输出

```
certx github.com:443

  ✓ 证书有效（剩余 87 天）
  ✓ 证书链验证通过

  TLS     TLSv1.3  TLS_AES_256_GCM_SHA384

[0] Leaf  github.com
    Subject  CN=github.com
    Issuer   CN=Sectigo Public Server Auth CA DV E36, O=Sectigo, C=GB
    Valid    2026-03-06  →  2026-06-03
    Status   剩余 87 天
    Serial   1DC289C1EADAFB04E9D1CF53D5D72253
    SHA-256  97:16:D3:94:41:CA:65:1C:51:BE:78:E9:69:CA:38:5E:...
    SAN      DNS:github.com, DNS:www.github.com  ✓ 匹配 github.com

[1] Intermediate  Sectigo Public Server Authentication CA DV E36
    ...

[2] Intermediate  Sectigo Public Server Authentication Root E46
    ...
```

## 颜色规则

| 剩余天数  | 颜色 | 含义 |
|----------|------|------|
| ≥ 30     | 绿   | 安全 |
| 14 – 30  | 黄   | 即将过期，提醒续期 |
| 0 – 14   | 红   | 紧急 |
| < 0      | 红   | **已过期** |

Leaf 证书的 SAN 行会自动检查是否匹配你访问的域名（含 `*.example.com` 通配）。

## 退出码

- `0`：证书有效且链验证通过
- `1`：连接失败 / 拿不到证书 / 参数错误
- `2`：证书已过期

适合脚本：`certx example.com -j | jq '.certs[0].days_left'`，或：

```bash
if ! certx example.com >/dev/null; then
    notify "证书要过期了"
fi
```

## 依赖

- `python3`（macOS 自带）
- `openssl`（macOS / Linux 自带；macOS 自带 LibreSSL，homebrew 装 openssl 也行）

## License

MIT
