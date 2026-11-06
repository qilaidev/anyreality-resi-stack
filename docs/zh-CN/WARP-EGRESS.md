# 服务端选择性 Cloudflare WARP 分流出口 (`--with-warp`)

> **一句话总结：** 住宅 IP 是你的核心资产，**绝不能做全量 WARP 全局出口**（那会把你花高价买的原生住宅 IP 降级成满大街共用的 Cloudflare 机房段）。本项目的 `--with-warp` 在服务端 `sing-box` 内部挂载原生 WireGuard Endpoint (`warp-ep`)，通过**严格的 10 级路由与 C9 顺序不变量**，仅把“因 ASN 被误伤弹 403/Turnstile 的 AI 与社交平台”以及“仅发布 AAAA 记录的 `challenges.cloudflare.com` 验证组件”精准切入 WARP，而 Google、Netflix、Disney+、TikTok、网银等继续保持 100% 原生住宅 IP 直出。

---

## 1. 为什么住宅 IP 节点还需要选择性 WARP？

即便你买到了干净的美国家宽 / ISP 租赁静态住宅 IP，日常使用中依然会遇到两个垂直痛点：

1. **AI 与内容平台的 ASN / IP 段误伤（403 / Turnstile 循环）**：
   `claude.ai`、`chatgpt.com`、`perplexity.ai`、`x.com`、`reddit.com`、`medium.com` 等站点经常按整个 `/24` 或 ASN 启用高敏 Cloudflare Bot Fight 策略。某些住宅 ISP 段或小型双ISP段会被无差别弹出验证。
2. **纯 IPv4 VPS 上的 Cloudflare Turnstile 死锁（AAAA-only 组件）**：
   Cloudflare 验证组件的核心子域（如 `brunhild.challenges.cloudflare.com`）**长期只发布 IPv6 AAAA 记录，没有 IPv4 A 记录**。如果你的住宅 VPS 只有 IPv4（且配置了 `"ip_version": 6, "action": "reject"` 防止 IPv6 黑洞卡死），客户端访问任何弹验证码的页面都会永远转圈。

### 为什么不能用通用一键脚本的“全局套 WARP”？
市面上通用脚本（如 `fscarmen/warp`、`233boy` 的全局 WARP 出站）会把整台节点的默认出口改成 WARP：
- **后果**：Netflix 自制剧以外锁区、Google 频繁弹异地或机房验证码、PayPal / Stripe / 网银风控告警、TikTok 识别为机房代理。你花几十美元买的住宅 IP 完全作废。

---

## 2. 本栈的 10 级选择性路由架构（C9 不变量）

启用 `--with-warp`（或运行 `/usr/local/sbin/anyreality-resi-stack-warp enable`）后，`scripts/warp_egress.py` 会在 `/etc/sing-box/conf/` 下生成 `02_warp_endpoints.json`，并重写 `03_route.json` 与 `05_dns.json`。

`03_route.json` 严格执行以下 **10 级顺序**（由 `warp_egress.py audit` 与 `healthcheck.sh` 强制校验）：

| 顺序 | 匹配条件 | 动作 / 出站 | 为什么必须在这个位置（踩坑教训） |
|---:|---|---|---|
| 1 | `action: sniff` | 嗅探 TLS SNI / HTTP Host | 必须在第一位，否则按 IP 连接的流量拿不到域名后缀 |
| 2 | `ip_is_private: true` | `direct` | 局域网与本机回环保护 |
| 3 | `domain_suffix: [challenges.cloudflare.com]` | `warp-ep` | **必须在第 4 步 `ip_version: 6` 拦截之前！** 因为 Turnstile 子域只有 AAAA 记录，借助 `warp-ep` 隧道自带的 `/128` IPv6 出口即可在纯 IPv4 机器上秒过验证 |
| 4 | `ip_version: 6` | `action: reject` | 拦截其余非 WARP 的 IPv6 流量，防止无公网 IPv6 的机器连接超时 |
| 5 | `inbound: [warp-probe-in]` | `warp-ep`（永久钉死） | 供 `127.0.0.1:10809` 探针专用。**即使 Watchdog 处于降级态也永远指向 `warp-ep`**，否则一旦降级就再也测不到隧道恢复 |
| 6 | `domain_suffix: EXCLUDE_DIRECT` | `direct` | **必须在 `WARP_SUFFIX` 与 `CF_CIDRS` 之前！** 保护 Google、YouTube、Apple、Microsoft、GitHub、Netflix、Disney+、TikTok、PayPal、Stripe、Speedtest 等永远走原生住宅 IP（哪怕它们的某些子域挂在 Cloudflare CDN 后） |
| 7 | `domain_suffix: WARP_SUFFIX` + `domain: WARP_EXACT` | `warp-ep` | 精准命中 `claude.ai`、`anthropic.com`、`chatgpt.com`、`openai.com`、`perplexity.ai`、`x.com`、`reddit.com`、`medium.com` 等 |
| 8 | `inbound: [hy2-in, vless-ws-in]` | `direct` | 高吞吐 UDP/CDN 通道的非 WARP 域名直接放行，跳过后续 DNS 解析匹配 |
| 9 | `action: resolve, strategy: ipv4_only` | 解析目标域名为 IPv4 | **必须在第 10 步 `ip_cidr` 之前！** 未经过 `resolve` 的域名流量在 sing-box 中永远不会命中 `ip_cidr` 规则 |
| 10 | `ip_cidr: CF_CIDRS` | `warp-ep` | 兜底命中 Cloudflare 官方 15 个 IPv4 边缘网段上的其余长尾站点 |

未命中以上规则的所有流量走 `final: direct`（原生住宅 IP 出站）。

---

## 3. 自动降级与自愈守护进程 (`warp-watchdog.timer`)

免费 Cloudflare WARP 节点偶尔会遇到对端 Endpoint 维护或握手僵死。如果 `warp-ep` 挂死而路由表不切换，Claude / ChatGPT 就会全部断网。

本栈内置了零外部依赖的状态机守护进程（每 2 分钟由 `warp-watchdog.timer` 触发一次 `warp_egress.py watchdog`）：

```text
[正常态: outbound = "warp-ep"]
   │
   ├─ 经 127.0.0.1:10809 (warp-probe-in) 请求 https://cp.cloudflare.com/generate_204
   │
   ├─ 连续 3 次失败 (约 6 分钟)
   ▼
[降级态: 自动改写 03_route.json 中 WARP 规则为 "direct" 并重载 sing-box]
   │  （注：规则 #5 `warp-probe-in -> warp-ep` 保持不变，继续后台探测隧道）
   │
   ├─ 连续 3 次探测成功
   ▼
[自愈恢复: 自动切回 "warp-ep" 并重载 sing-box]
```

---

## 4. 常用命令

### 安装时一键开启
```bash
# 自动向 Cloudflare 注册免费 WireGuard 密钥对并开启选择性分流 + Watchdog
bash install/install.sh \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription \
  --with-warp
```

如果你已有现成的 WARP 凭据文件，可通过 `--warp-config /path/to/warp-credentials.json` 传入。

### 已安装节点随时启停或审计
系统安装后自带 `/usr/local/sbin/anyreality-resi-stack-warp` 命令：

```bash
# 1. 注册新的 WARP 凭据（保存在 /etc/anyreality-resi-stack/warp-credentials.json，权限 600）
anyreality-resi-stack-warp register

# 2. 启用选择性 WARP 出站
anyreality-resi-stack-warp enable --credentials /etc/anyreality-resi-stack/warp-credentials.json

# 3. 审计当前 03_route.json 是否满足全部 C9 顺序不变量（可选 --live-cf-ips 对比 Cloudflare 实时官方网段）
anyreality-resi-stack-warp audit --live-cf-ips

# 4. 手动触发一次 Watchdog 探测并查看状态 JSON
anyreality-resi-stack-warp watchdog

# 5. 双端口分流实测验证（对比原生出口 vs 走路由表的出口）
curl -x http://127.0.0.1:10809 https://cloudflare.com/cdn-cgi/trace   # 强制走 warp-ep，应显示 warp=on
curl -x http://127.0.0.1:10810 https://cloudflare.com/cdn-cgi/trace   # 走主路由表，CF 站点显示 warp=on
curl -x http://127.0.0.1:10810 https://ipinfo.io/ip                   # 命中 EXCLUDE_DIRECT，显示你的原生住宅 IP

# 6. 关闭 WARP 出站，恢复纯直连 03_route.json
anyreality-resi-stack-warp disable
```
