# 故障排查 | Troubleshooting

按"症状 → 最常见原因 → 修复"顺序排列。诊断永远是先看几个基础状态：

```bash
systemctl status sing-box --no-pager
journalctl -u sing-box -n 50 --no-pager
ss -tlnp | grep ':443'
ufw status verbose
sing-box check -C /etc/sing-box/conf
```

任何 issue 模板都会让你先粘贴这几条的输出。

---

## 客户端连不上

**先确认协议匹配。** 默认协议 `vless-reality` 两个生态都支持，正常情况下不会有协议不匹配问题。只有装成 `--protocol anytls-reality` 时才是 sing-box 系专用 —— 那种模式下服务端**根本不会生成 Clash 订阅**，所以 Clash 用户会发现订阅里没有 YAML 可用。

| 可能原因 | 排查 |
|---|---|
| 装了 `anytls-reality` 却要用 Clash | 用 `--protocol vless-reality` 重装（默认值） |
| 云厂商安全组没放 `443/tcp` | 登入控制台检查安全组 |
| UFW 没放 `443/tcp` | `ufw status` |
| `anytls-reality`：客户端 `password` 与服务端 `ANYTLS_PASSWORD` 不一致 | 比对客户端 password 与 `/etc/anyreality-resi-stack/secrets.env` 里的 `ANYTLS_PASSWORD` |
| `vless-reality`：客户端 UUID 不一致 | 比对客户端 vless:// 链接里的 UUID 与服务端 `secrets.env` |
| 客户端 Reality `public-key` 填错 | 比对客户端 `pbk=` / `public_key` 与服务端的 `REALITY_PUBLIC_KEY` |
| 客户端 Reality `short_id` 不一致 | 比对客户端 `short_id` 与服务端配置 |
| 客户端 `servername` / SNI 与服务端 `server_name` 不一致 | 都应该是同一个 SNI（如 `addons.mozilla.org`） |
| 客户端不支持 Reality（遗留还需 `xtls-rprx-vision`） | 用最新版 sing-box / v2rayN / Clash Verge |
| 服务器已有 nginx/caddy/apache 占 443 | `ss -tlnp \| grep 443` 看占用进程 |
| sing-box 配置有错 | `sing-box check -C /etc/sing-box/conf` |

> REALITY 入站配置文件同一时刻只应存在一个：`vless-reality` 是 `/etc/sing-box/conf/11_xtls-reality_inbounds.json`，`anytls-reality` 是 `11_anytls-reality_inbounds.json`。两个都在会抢 `443` 端口导致 `sing-box check` 报错。（`12_hysteria2_inbounds.json` 和 `13_vless-ws_inbounds.json` 是另外两条路径，与它们不冲突。）

---

## 客户端一点就退 / 开机起不来（重启电脑有时候好）

**症状**：客户端启动后立刻退出，或反复自动重启；重启电脑后有时能用、有时还是不行。

**根因**：sing-box **启动时**必须把所有 `type: remote` 的规则集下载完才继续，任何一个失败就
`FATAL` 退出。下载走 `download_detour` 指向的代理组，而**冷启动时 urltest 还没有任何测速结果，
只能取第一个成员** —— 那个成员在你这条线上如果是死的，就会超时、FATAL、被客户端重启、再撞同一堵墙。

"重启电脑就好了"只是时序变了、那次下载碰巧成功，**从来没真正修好**。

```bash
# 客户端日志里出现这个，就说明这个环还在
grep -c "raw.githubusercontent" "<你的客户端 kernel.log>"
```

**本项目下发的订阅规则集全部 `inline`，启动期零网络请求**，物理上不可能因下载失败而起不来。
如果还在发生，按顺序查：

1. **客户端里是否还留着已下线服务器的旧订阅**？它自带的 `type: remote` + `download_detour`
   会把死锁重新引进来 —— **即使它当前没被选中**。删干净。
2. 客户端本地是否缺 `.srs`？有些客户端（如 Sail）只自带三个规则集，遇到它没有的 tag 会拼成
   远程地址去拉。本机 sing-box 可以直接编译，不需要下载：
   ```bash
   sing-box rule-set compile --output geosite-private.srs geosite-private.json
   ```
3. 服务端确认订阅里确实没有 remote：
   ```bash
   python3 /usr/local/lib/anyreality-resi-stack/check_profile.py \
     /etc/anyreality-resi-stack/files/profile.json
   ```

详见 [国内网络优化 §3](CHINA-NETWORK.md)。

---

## CDN 中转能连上，但每隔约 2 分 05 秒断一次

**症状**：走 CDN 中转的连接反复在 **2m05s / 2m06s / 2m07s** 断开，精确得可疑。

**这三个方向都是错的**（都查过）：

| 怀疑对象 | 实际 |
|---|---|
| nginx `proxy_read_timeout` | 本项目模板里是 3600s，不可能产生 125 秒 |
| 客户端 TCP keepalive / `keep-alive-idle` | TCP keepalive 是**逐跳**的，在 CDN 边缘就终止，CDN 根本看不见 |
| 「自动组选错了节点」 | 换哪个节点都一样 |

**真凶是 CDN 对被代理 WebSocket 的空闲超时**（普通套餐约 100 秒）：双向都没有帧就关闭。
保活必须靠**应用层 ping**（真的变成 WS 帧的那种），而 sing-box 的 h2mux/smux/yamux 都不发。

本项目用源站侧注入解决。先确认它活着：

```bash
systemctl status ws-ping-inject
ss -tlnp | grep 18444          # 注入器在监听
nginx -T | grep -F "<你的 WS 路径>"   # 注意是 -T（运行态），不是 -t
```

`ws-ping-inject` 挂掉 = CDN 隧道全部按约 100 秒掉线，而 sing-box 和 nginx 都显示正常。
体检脚本会专门报这一项。

---

## Hysteria2 装了，服务端一切正常，但所有客户端都连不上

**十有八九是防火墙只放行了 TCP。** `ufw allow 443` **只开 TCP**，UDP 要单独写：

```bash
ss -ulnp | grep ':443'                    # 服务端确实在监听 UDP
ufw status | grep -E '443/(tcp|udp)'      # 两条都要有
ufw allow 443/udp comment "hysteria2"     # 缺了就补
```

这个坑的恶劣之处在于：入站配置合法、进程在监听、`sing-box check` 通过、日志干净 ——
**从服务端完全看不出问题**，只有客户端超时。

---

## 备用端口在 `ss -tlnp` 里看不到

**这是预期行为，不是故障。** 备用端口是 `nat/PREROUTING` 里的 REDIRECT，不是新的监听：

```bash
iptables -t nat -S ANYREALITY_ALTPORT      # 规则在这里
iptables -t nat -L ANYREALITY_ALTPORT -v -n  # pkts/bytes 才是真实使用量
```

也因为改写发生在 filter/INPUT **之前**，UFW 不需要为备用端口放行 —— 别去加多余的规则。

---

## TG / Discord 上传卡死、语音卡顿

这是**最常见的"住宅 IP 软风控"**症状，**不是协议问题**。

**症状判定：**
- 客户端测速能跑满
- 普通文字消息正常
- 大文件、语音、视频上传质量明显下降
- 同一账号在原生网络下没事

**根因：** 你的住宅 IP 所在 /24 子网历史上有人跑过 bot，Telegram/Discord 的反滥用系统已经把整段 IP 信誉降级 —— 这跟你这个具体账号无关，纯粹是连坐。

**解决方案：** 双节点 + 智能分流（按域名把 TG/Discord 走数据中心节点）。详见 [DUAL-NODE.md](DUAL-NODE.md)。

**临时方案**（不动服务端，5 分钟）：在客户端 Clash YAML 加一段路由规则，把 TG/Discord 流量丢给一个非住宅 IP 的备用代理（哪怕是另一个普通机场）。规则示例：

```yaml
rules:
  - DOMAIN-SUFFIX,telegram.org,你的备用节点名
  - DOMAIN-SUFFIX,t.me,你的备用节点名
  - DOMAIN-SUFFIX,discord.com,你的备用节点名
  - IP-CIDR,91.108.4.0/22,你的备用节点名,no-resolve
  - IP-CIDR,91.108.16.0/22,你的备用节点名,no-resolve
  - IP-CIDR,149.154.160.0/20,你的备用节点名,no-resolve
  # 其它走默认 PROXY
```

---

## 订阅 URL 能打开，但客户端不显示流量卡片

```bash
curl -I http://你的服务器IP/你的token
```

必须看到这几个响应头：

- `Subscription-Userinfo`
- `Profile-Title`
- `Profile-Update-Interval`

如果都有，但客户端不显示 → 是**客户端版本不支持**这个卡片渲染（v2rayN 4.x 之前、某些 Clash 移动端），不影响代理本身。换支持的客户端即可。

如果响应头缺失 → 检查 `subscription-leaf.service` 日志：

```bash
journalctl -u subscription-leaf -n 50 --no-pager
```

---

## 流量统计与商家后台对不上

**短答：** 这是**预期行为**，不是 bug。

**长答：** 订阅服务统计的是 `/sys/class/net/<iface>/statistics/rx_bytes + tx_bytes` 在当前配置账期内的累计差值。商家计费可能：

- 按出方向计费（你的 tx_bytes 而不是 rx + tx）
- 按 95 百分位计费（不是累加）
- 按五分钟峰值计费
- 加上控制层流量（DHCP / ARP / 你自己 SSH 进去看的流量）
- 商家账期从特定日期开始，例如每月 11 号，而不是每月 1 号

**校准方法**（让订阅卡片从这一刻起跟商家后台对齐）：

```bash
CURRENT_TOTAL=$(( $(cat /sys/class/net/eth0/statistics/rx_bytes) + $(cat /sys/class/net/eth0/statistics/tx_bytes) ))
STATE_USED=$(python3 -c "import json; print(int(json.load(open('/var/lib/anyreality-resi-stack/usage-state.json'))['used_bytes']))")
BACKEND_USED=900000000000   # 替换成商家后台显示的本月已用字节数

OFFSET=$((BACKEND_USED - STATE_USED))
sudo sed -i "s/^USAGE_OFFSET_BYTES=.*/USAGE_OFFSET_BYTES=${OFFSET}/" /etc/anyreality-resi-stack/subscription-leaf.env
sudo systemctl restart subscription-leaf
```

如果商家不是每月 1 号重置流量，先把 `BILLING_CYCLE_DAY` 设成商家重置日：

```bash
sudo sed -i "s/^BILLING_CYCLE_DAY=.*/BILLING_CYCLE_DAY=11/" /etc/anyreality-resi-stack/subscription-leaf.env
```

如果 `usage-state.json` 还不存在或刚被恢复清空，leaf 会在下一次后台采样或 `/status` 请求时自动建状态。`USAGE_OFFSET_BYTES` 可以为负数；服务端会把最终返回值钳到不低于 0。

---

## TLS 自握手失败 / Reality 似乎没生效

```bash
echo | openssl s_client -connect 127.0.0.1:443 -servername addons.mozilla.org 2>/dev/null | grep subject=
```

应该返回 `addons.mozilla.org` 的证书 subject。如果返回别的（比如 sing-box 的自签证书 / `cannot connect`）：

- **没装 sing-box / 没启动**：`systemctl status sing-box`
- **SNI 配错**：检查 REALITY 入站文件（`11_xtls-reality_inbounds.json` 或 `11_anytls-reality_inbounds.json`）里的 `tls.server_name` 和 `tls.reality.handshake.server` 必须**完全一致**
- **服务器到 SNI 站的握手网络出问题**：服务器自己 `curl -v https://addons.mozilla.org/` 看能不能成
- **Reality 私钥与客户端公钥不匹配**：在服务器重新跑 `sing-box generate reality-keypair` 获取一对，更新服务端 `private_key` 和客户端 `public-key`

---

## fail2ban 把我自己锁了

```bash
fail2ban-client status sshd                   # 看被封 IP
fail2ban-client set sshd unbanip 1.2.3.4      # 解封
```

预防：在 `--harden-ssh` 之前确保有备用 SSH 会话；fail2ban 默认 5 次失败封 1 小时。

---

## 升级 sing-box 后服务起不来

```bash
journalctl -u sing-box -n 100 --no-pager
sing-box check -C /etc/sing-box/conf
```

最常见原因：新版 sing-box 改了 schema。把错误信息搜 [sing-box 官方 changelog](https://github.com/SagerNet/sing-box/releases)。短期处理：

```bash
apt-get install -y sing-box=<上一个能跑的版本号>
apt-mark hold sing-box   # 暂时不让 apt 升级
```

再到 anyreality-resi-stack 这边开 issue。

---

## NTP 时间同步失败

```bash
timedatectl
chronyc sources -v
```

多个 NTP 源 `Reach=0` 通常是 VPS 厂商封了 `123/UDP` 出站。这**不阻塞代理转发**（VLESS 不依赖时钟严格同步），但会让日志时间戳错乱。可以换到 NTS（TLS 化的 NTP）：

```bash
sudo sed -i 's|^pool .*|pool time.cloudflare.com iburst nts|' /etc/chrony/chrony.conf
sudo systemctl restart chrony
```

---

## 配置改坏 / 想回滚

```bash
ls /var/backups/anyreality-resi-stack/
# 选一个时间戳较新的
tar -tzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-2026-05-17-120000.tar.gz | head
```

恢复（先停服务）：

```bash
systemctl stop sing-box
tar -xzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz -C /
systemctl daemon-reload
systemctl start sing-box
sing-box check -C /etc/sing-box/conf
```

⚠️ 备份归档**不含** `/var/lib/anyreality-resi-stack/usage-state.json`、`usage-cache.json`（运行时数据）和 sing-box 日志，所以恢复后流量计数会从恢复时刻重新起算。归档会包含 `/etc/anyreality-resi-stack/`，里面有密钥和 token，不能公开传播。恢复后可以用上面"流量统计漂移"小节的命令补一个 offset。

完整的备份校验、恢复演练和回滚流程见[运维手册](OPERATIONS.md)。

---

## 出口 IP 不是预期的住宅 IP

```bash
curl --proxy socks5h://127.0.0.1:7891 https://ipinfo.io
```

如果返回的 IP 不是你的住宅 IP：

- 客户端规则可能把请求走了另一个节点 → 看客户端规则匹配日志
- DNS 污染：客户端没有用 SNI 嗅探就走了 Direct → 检查 Clash 的 `mode: rule` 与 `dns:` 段
- 你的住宅节点已经挂了，客户端自动 fallback 到了备用节点 → `systemctl status sing-box` on the residential node

---

## Cloudflare 人机验证一直转圈 / 永远过不去

**先分清两个独立问题，它们的原因完全不同：**

| 症状 | 原因 | 看哪一节 |
|---|---|---|
| **经常弹**验证，但点一下能过 | 出口 IP 的 ASN 信誉差（廉价 VPS 段被 CF 判高风险） | 下面「经常弹验证」 |
| 验证页**一直转圈**、反复要求验证、点了没反应 | 验证控件加载不出来 —— 多半是 IPv6 | 本节下面这段 |

### 一直转圈过不去 → 十有八九是节点没有 IPv6

Cloudflare 的验证控件从 `brunhild.challenges.cloudflare.com` 加载，
这个域名**长期只有 AAAA 记录、没有 A 记录**（对 1.1.1.1 / 8.8.8.8 / 9.9.9.9 三方核对过）。
如果节点没有可用的 IPv6 出口，控件的 JS 根本下载不下来，验证自然永远完不成。

这个故障**极难自己联想到**：服务器上唯一的痕迹就是 error 日志里的一行

```
lookup brunhild.challenges.cloudflare.com: empty result
```

**先确诊：**

```bash
# 1) 节点有没有全局 IPv6 地址（0 就是没有）
ip -6 addr show scope global | grep -c inet6

# 2) 能不能真的走 IPv6 出去
curl -6 -sS --max-time 8 -o /dev/null -w '%{http_code}\n' https://brunhild.challenges.cloudflare.com/

# 3) 日志里这个域名的报错按天分布（能定位是哪天开始的）
journalctl -u sing-box --no-pager | grep -c "empty result"
```

`anyreality-resi-stack-healthcheck` 已经内置这项检查，没有 IPv6 时会直接告警。

**修复，按优先级：**

1. **给 VPS 开 IPv6**（最彻底）。绝大多数厂商免费送 /64，在面板启用后配好网卡即可。
   开完再跑一次上面第 2 条确认。
2. 本仓库模板已经为这个域名放开了 IPv6 解析
   （`templates/singbox/05_dns.json` 里 `challenges.cloudflare.com` → `prefer_ipv4`：
   有 A 就用 A，只有 AAAA 就用 AAAA）。老节点重装或手工同步这段配置即可。
   ⚠️ 注意 sing-box 1.12+ 的 `strategy` 属于 **DNS 规则的 `action: route`**，写在 server 里会报
   `unknown field "strategy"`。
3. 如果确实拿不到 IPv6：只能接受重验证类站点不可用，或给节点挂一条 IPv6 隧道
   （WARP / HE.net 之类）再把该域名指过去。

> **客户端侧的修复必须在 DNS 段，不能只放路由规则。** TUN 模式（本项目推荐的用法）下，
> 应用是**先查 DNS、再发起连接**的 —— 查询在 `ipv4_only` 下已经返回空，路由规则根本轮不到。
> 所以客户端模板在 `dns.rules` 里给该后缀单独开了 `prefer_ipv4`（经节点解析）；
> 路由层那条把它钉到节点的规则一并保留，成本为零且语义明确。改这段时两处都别删。

### 经常弹验证（但能过）→ 出口 ASN 信誉问题

和协议、SNI、伪装、客户端**全都无关**，换协议或改 SNI 都不会有任何改善。
先确认出口属于哪个 ASN：

```bash
curl -sS https://ipinfo.io/org      # 在节点上跑
dig -x <你的节点IP> +short          # rDNS 常常直接暴露上游机房
```

如果落在廉价 VPS 转售最集中的那几个 ASN（例如 ColoCrossing 一类），
CF 会按**概率**下发质询 —— 所以表现是"经常"而不是"总是"。这也是本项目
推荐**住宅 IP**出口的根本原因：住宅段的信誉分天然就高。

可选缓解：把受影响的域名单独走一个信誉更好的出口（本项目的双节点分流就是干这个的，
见 [DUAL-NODE.md](DUAL-NODE.md)）。

> ⚠️ **测量陷阱**：用普通 `curl` 测 CF 站点会一律返回 `403`，这是因为 curl 没有浏览器的
> TLS/HTTP2 指纹、也不执行 JS，**不代表你的 IP 有问题**。要判断 IP 是否真被质询，
> 必须用带真实指纹的客户端（如 Python 的 `curl_cffi`，`impersonate="chrome131"`），
> 判据是响应头里的 `cf-mitigated: challenge`。

---

## 还没解决？

提 issue 时带上：

- `journalctl -u sing-box -n 100 --no-pager`
- `sing-box version`
- `cat /etc/os-release | head -3`
- 期望 vs 实际行为
- **不要** 粘贴 UUID / Reality 公私钥 / 服务器 IP

模板会再提醒一次。

相关文档：

- 第一次部署：先看 [新手完整教程](BEGINNER_GUIDE.md)
- 判断是否该上双节点：看 [双节点 + 智能分流](DUAL-NODE.md)
- 还在选 3x-ui / x-ui / 手写配置：看 [同类评分对比](COMPARISON.md)
