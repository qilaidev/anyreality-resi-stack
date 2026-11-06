# 常见问题 FAQ | anyreality-resi-stack

**一句话**：`anyreality-resi-stack` 是在你自有 Ubuntu/Debian VPS 上用 `install/install.sh` 部署 **sing-box AnyReality（AnyTLS+REALITY，默认）** 的开源自托管工具包；可选遗留 VLESS+Vision、Python 订阅与双节点分流。不是卖 IP、不是机场面板。

每个答案尽量给出可执行命令，并指向深入文档。English: [docs/en/FAQ.md](../en/FAQ.md)。README 精简 FAQ：[README.md](../../README.md#-faq)。

- [项目定位](#项目定位)
- [协议与客户端](#协议与客户端)
- [安装与部署](#安装与部署)
- [订阅服务](#订阅服务)
- [分流与网络行为](#分流与网络行为)
- [双节点](#双节点)
- [运维与安全](#运维与安全)
- [许可与边界](#许可与边界)

---

## 项目定位

### anyreality-resi-stack 是什么？

它是一个开源（GPL-3.0）的自托管代理部署工具包。用一条 Bash 命令在你**自己的** Ubuntu 22.04+ / Debian 12+ VPS 上部署 sing-box 节点，默认协议是 **AnyReality（AnyTLS + REALITY）**，并可选安装零依赖 Python 订阅服务、流量卡片和双节点域名分流。入口是 [`install/install.sh`](../../install/install.sh)。

### 它和 3x-ui / x-ui / XHTTP-Installer 有什么区别？

那些工具面向「便宜 VPS + 多用户 + Web 面板 + 尽量隐藏出口 IP」。本项目的前提相反：**住宅 IP 是资产**。所以它默认单用户、无 Web 面板（少一个暴露面）、不隐藏出口 IP，只把对住宅 IP 不友好的少数服务按域名旁路走备用节点。需要多用户、到期时间、流量限额和管理员 API 时，3x-ui / x-ui 更合适。评分对比见 [COMPARISON.md](COMPARISON.md)。

### 它提供住宅 IP 或服务器吗？

不提供。这是一个**配置工具**，不是资源供应商。你需要自己准备 VPS（住宅 IP VPS 或普通数据中心 VPS 都能装）。

### 谁适合用它？

有自己的 VPS、会基本 SSH、希望少维护面板的个人开发者、小团队、AI 工具用户和跨设备代理用户。第一次部署请走 [新手完整教程](BEGINNER_GUIDE.md)。

### 需要什么前置条件？

一台 Ubuntu 22.04+ / 24.04 LTS 或 Debian 12+ 的 VPS，root 或 sudo 权限，能 SSH 登录，安全组/防火墙允许 `443/tcp`（启用订阅服务时再加 `80/tcp`）。不需要域名，不需要 TLS 证书，不需要 Docker。

---

## 协议与客户端

### 默认协议是什么？AnyReality 和 VLESS+Reality 怎么选？

默认是 **VLESS + REALITY + xtls-rprx-vision**（`--protocol vless-reality`）。选它不是因为它抗检测最强，
而是因为它是**唯一一个 sing-box 与 mihomo 都能写出来**的抗检测协议。

**为什么不是 AnyReality。** 本仓库以前默认 AnyReality，填充确实更强，但 mihomo 的 `anytls` 配置块
没有 `reality-opts` 字段 —— Clash 订阅里那个节点**根本写不出来**。而服务端全绿、`sing-box check`
通过、sing-box 用户完全正常，**只有 Clash 用户没有主力节点，且看到的不是任何报错**。拖了一个月。

**怎么选（决策树）：**

1. 客户端里有 Clash / mihomo / Stash，或者不确定 → **默认 `vless-reality`，别改。**
2. 确定所有客户端都是 sing-box 系，且想要更强的填充 → `--protocol anytls-reality`，
   代价是**不生成 Clash 订阅**（安装器会明确告诉你）。

```bash
# 只在确定不需要 Clash 时
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" --protocol anytls-reality --with-subscription
```

两者都不需要域名和证书。完整论证见 [README · 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。
切换协议要重跑安装器并**重新导入客户端**（凭据形态与订阅格式都会变）。

### 哪些客户端能用？

默认协议下**两个生态都能用**：sing-box 系（SFA / SFI / SFM、Karing、Hiddify、NekoBox）和
Clash 系（Clash Verge、mihomo、Stash）。订阅只有一个 URL，服务端按 User-Agent 决定返回
`profile.json` 还是 `profile.yaml`。只有 `--protocol anytls-reality` 会把范围缩到 sing-box 系。
各客户端导入步骤见 [CLIENTS.md](CLIENTS.md)。

### Reality 需要域名和证书吗？

不需要 —— 这是它相对 Trojan / V2Ray-TLS 的最大优势。默认伪装 SNI 是 `addons.mozilla.org`，你可以用 `--sni` 换成任何真实可访问、高信誉的 HTTPS 站点。

### 手动导入 AnyReality 要填哪些字段？

`type=anytls`、`server`、`port`、`password`、`tls.server_name=<SNI>`、`utls fingerprint=chrome`、`reality public_key`、`short_id`。这些值在安装完成卡里，也可以从服务器上取：

```bash
grep -E '^(ANYTLS_PASSWORD|REALITY_PUBLIC_KEY|SHORT_ID)=' /etc/anyreality-resi-stack/secrets.env
```

### 装完之后凭据在哪里？

`/etc/anyreality-resi-stack/secrets.env`（权限 600）。完成卡只打印一次，凭据本身不会丢。

---

## 安装与部署

### 一行安装命令是什么？

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

更多命令配方（改端口、固定版本、无人值守、双节点）见 [EXAMPLES.md](EXAMPLES.md)。

### 安装脚本到底做了什么？

系统预检 → BBR / swap / journald 限额 → 从 Sagernet 官方 apt 源装 sing-box（校验 GPG 指纹）→ 生成 UUID、Reality 密钥对、AnyTLS 密码、订阅 token → 渲染 `/etc/sing-box/conf` → 启用 systemd 服务 → UFW + fail2ban → 可选订阅服务 → 每日配置备份 timer → 端到端自检。想先看不执行，加 `--dry-run`。

### 能先预览再执行吗？

可以，强烈建议第一次这样做。`--dry-run` 只打印将要执行的命令，不改动任何系统状态：

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --dry-run
```

### 安装脚本能重复运行吗？会把 UUID 和 Reality 密钥洗掉吗？

脚本是**幂等**的。重跑不会改 UUID，也不会重新生成 Reality 密钥对，重复执行的阶段是 no-op。另外每天有 systemd timer 自动备份 sing-box 配置到 `/var/backups/anyreality-resi-stack/`（保留最近 3 份）。

### 怎么固定版本，做可重复部署？

用 `ANYREALITY_RESI_STACK_REF` 指定 tag 或分支，不要跟着 `main` 漂：

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" --with-subscription
```

要固定 sing-box 自身的版本，再加 `--singbox-version <apt-package-version>`；apt 源里没有该版本时安装会直接失败，不会带着错版本继续。

### 怎么无人值守 / 自动化安装？

把所有值写进一个 `KEY=VALUE` 文件，再配 `--non-interactive`：

```bash
bash <(curl -fsSL .../install.sh) --config /root/install.env --non-interactive
```

变量清单见 [DEPLOYMENT.md](DEPLOYMENT.md#2-变量表)。缺 `--node-name` 时非交互模式会直接报错而不是卡在提示符上。

### 公网 IP 探测失败怎么办？

安装器会自动探测公网 IP。探测不到时（非 `--dry-run`）会直接停止，提示你在 `--config` 文件里设置 `SERVER_IP=<你的公网IP>`。这是有意的 —— 否则客户端配置会被渲染成不可用的空 server。

### 端口 443 被占用，能换吗？

可以，`--inbound-port <N>`。UFW 规则、客户端配置和卸载清理都会跟着这个端口走。但 443 最不显眼，能不换就不换。

### 支持 CentOS 7 / Alpine / OpenWRT / Docker / Kubernetes 吗？

都不支持，而且是有意的。BBR、journald 限额、sing-box apt 源和 GPG 指纹校验都依赖现代 systemd + apt。用更小的兼容矩阵换稳定性。Docker / K8s 支持也明确列在 [CONTRIBUTING.md](../../CONTRIBUTING.md) 的 out-of-scope 里。

### 从 v1.x（reality-resi-stack）升级要注意什么？

直接重跑安装器即可。v2.0 把运行时路径、systemd 单元、备份脚本和归档统一到 `anyreality-resi-stack` 前缀，安装器会自动就地迁移旧的 `/etc/reality-resi-stack`、`/var/lib/reality-resi-stack`，**不丢密钥、状态和备份**。旧的 `REALITY_RESI_STACK_REF` 环境变量仍然被兼容。

### 怎么升级 sing-box？

```bash
apt-get update && apt-get install --only-upgrade -y sing-box
systemctl restart sing-box
sing-box version
sing-box check -C /etc/sing-box/conf
```

### 怎么卸载？

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh
```

默认**保留** `/etc/anyreality-resi-stack/`（密钥）和 `/var/backups/anyreality-resi-stack/`（备份）。要连凭据一起清掉用 `--purge-all` —— 删除后无法恢复，所有客户端订阅立即作废。注意卸载脚本不会移除 sing-box 二进制（由 apt 管理，需要的话自己 `apt-get remove sing-box`）。

---

## 订阅服务

### 订阅服务是干什么的？必须装吗？

不是必须的。它是一个零依赖 Python HTTP 服务（[`subscription/leaf_server.py`](../../subscription/leaf_server.py)），让客户端能用一个 URL 自动同步配置，并通过 `Subscription-Userinfo` 响应头显示流量卡片。不装的话，就手动把客户端配置从服务器 `scp` 下来导入。设计细节见 [SUBSCRIPTION.md](SUBSCRIPTION.md)。

### 订阅 URL 是 HTTPS 吗？能公开分享吗？

**不是 HTTPS，是明文 HTTP :80**，而且返回的配置里含节点凭据（AnyReality 密码或 VLESS UUID）。**拿到 URL 就等于拿到你的节点。** 绝不要贴进 issue、截图或聊天群。需要加密就自己在前面加一层 TLS 反代，或者 `scp` 取一次配置后把订阅服务关掉。完整说明见 [SECURITY.md](../../SECURITY.md#subscription-url-exposure--订阅地址的暴露面)。

### 订阅 URL 忘了怎么找回？

```bash
grep ^SUB_TOKEN /etc/anyreality-resi-stack/secrets.env
# 订阅地址就是 http://<你的公网IP>/<SUB_TOKEN>/
```

### 订阅能打开，但客户端不显示流量卡片？

先确认服务在跑、响应头带 `Subscription-Userinfo`：

```bash
curl -fsS http://<your-ip>/healthz
curl -sI http://<your-ip>/<SUB_TOKEN>/ | grep -i subscription-userinfo
```

如果 `total=0`，说明安装时没设 `--total-bytes`，卡片会隐藏配额。逐项排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md#订阅-url-能打开但客户端不显示流量卡片)。

### 流量统计和商家后台对不上？

本项目统计的是**网卡 RX+TX 总量**，商家后台的口径、计费周期起点、是否只算出站都可能不同，短期漂移是正常的。用 `--billing-cycle-day` 对齐商家的重置日，用 `USAGE_OFFSET_BYTES` 补齐安装之前已经用掉的量。语义和排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md#流量统计与商家后台对不上)。

### 能不能把别的文件放进订阅目录？

**不要。** `FILE_DIR` 里的任何文件都能通过同一个 token 路径 `/<TOKEN>/<filename>` 被下载。备份归档、密钥文件绝对不能放进去。

---

## 分流与网络行为

### 刚导入订阅，国内网站（淘宝、微信、B 站、网银）就变慢了，是节点问题吗？

不是。TUN 模式下**没有「全局 / 直连」开关**，流量走不走代理完全由规则决定，规则不完善就会把国内流量也发去海外。本项目下发的客户端配置**自带四层分流规则**：内网直连 → 广告拦截 → 国内域名/IP 直连 → 兜底走节点，导入即用。如果你手改过配置或用了别处的模板，对照 [ROUTING.md](ROUTING.md) 检查。

### 为什么在 `geosite-cn` 之外还内联了一份国内域名列表？

因为 `geosite-cn` / `geoip-cn` 规则集要从 GitHub 下载，首次启动下不来就整个失效，国内流量会全部涌向节点。所以本项目在它前面额外内联了约 60 条国内域名的安全网，不依赖任何网络请求，下载失败时国内站点仍然直连。见 [ROUTING.md](ROUTING.md#为什么-layer-2-要做两级)。

### 为什么默认拦掉 UDP 443（QUIC / HTTP3）？

AnyTLS + Reality 是纯 TCP 协议，QUIC 流量没法走节点。不拦的话浏览器会一直尝试 HTTP/3，超时后才回落 TCP，表现就是「打开网页先卡几秒」。拦掉 `udp:443` 是让它**立刻**回落 TCP。不需要这个行为就删掉那条规则，见 [ROUTING.md](ROUTING.md#想改默认行为)。

### 怎么给分流规则加自己的域名？

在客户端配置的 `domain_suffix` 数组里加一行，然后校验并让客户端刷新订阅。改模板的话要重新生成 `examples/`（仓库有漂移门禁）。完整步骤见 [ROUTING.md](ROUTING.md#增删国内平台)。

### 怎么确认某个域名确实走了直连？

三种办法：绕开环境代理直接测、把 sing-box 客户端日志调到 `info` 看这条连接实际走了哪个 outbound、或者直接看出口 IP。命令见 [ROUTING.md](ROUTING.md#验证某个域名确实走了直连)。

### 怎么验证出口 IP 就是我的住宅 IP？

导入的 sing-box 客户端默认在本地 `127.0.0.1:2080` 起一个混合代理：

```bash
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com
```

返回的应该是你 VPS 的公网 IP。不对的话见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md#出口-ip-不是预期的住宅-ip)。

---

## 双节点

### Telegram 在住宅 VPS 上文件上传卡死、"正在发送…" 一直转，怎么办？

Telegram 会对**历史上跑过 bot 的住宅 IP 段**做软降权。启用**双节点模式**，把 `geosite:telegram` 通过数据中心备用节点出去即可。原理和部署步骤见 [DUAL-NODE.md](DUAL-NODE.md)。

### OpenAI / ChatGPT 在数据中心 VPS 上提示 "unsupported region"，换住宅 VPS 就好了 —— 但 Telegram 又变慢，怎么两个都顾？

这就是这个项目存在的理由：**OpenAI / Anthropic / 银行 / Netflix 走住宅出口，Telegram / Discord 走数据中心节点**，客户端只订阅一个 URL，配置里同时含两个节点和分流规则。

### 双节点需要几台服务器？必须用吗？

需要两台（一台住宅 leaf + 一台数据中心 aggregator），**不是必须的**。只有一台服务器、或者 Telegram / Discord 本来就不卡时，单节点 `--with-subscription` 就够了。需不需要的决策树见 [DUAL-NODE.md](DUAL-NODE.md#决策树你需不需要双节点)。

### 双节点客户端要配两个订阅吗？

不用。客户端只订阅 aggregator 的 URL，返回的单个配置里已经同时包含两个节点和分流规则，客户端不需要任何额外配置。

### leaf 短暂离线，流量卡片会归零吗？

不会。aggregator 在后台轮询 leaf 的 `/<TOKEN>/status` 并缓存最后一次成功结果，leaf 不可达时回退到缓存，避免"已用 0"的跳变。见 [DUAL-NODE.md](DUAL-NODE.md#缓存回退的实际效果)。

---

## 运维与安全

### 怎么看服务状态和日志？

```bash
systemctl status sing-box --no-pager
journalctl -u sing-box -n 100 --no-pager
systemctl status subscription-leaf --no-pager    # 或 subscription-aggregator
curl -fsS http://<your-ip>/healthz
```

### 会不会把我的密钥提交到 Git？

每台服务器本地生成独立的 UUID / Reality 密钥 / AnyTLS 密码 / 订阅 token，仓库里永远不存真实值。仓库自带脱敏扫描（`make redact`）和哈希 denylist，CI 强制门禁；`examples/` 里的值全是 RFC 5737 文档 IP 和哨兵字符串，不可用于真实部署。

### fail2ban 把我自己锁了怎么办？

从另一个 IP 或服务商的 VNC / 串口控制台登录后解封。命令见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md#fail2ban-把我自己锁了)。所以 `--harden-ssh` 默认是关的。

### 配置改坏了怎么回滚？

每日 timer 会把配置备份到 `/var/backups/anyreality-resi-stack/`（保留最近 3 份）。挑一个较新的归档解开还原，步骤见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md#配置改坏--想回滚)。注意备份里含 `/etc/anyreality-resi-stack/`（凭据），归档本身要当作敏感文件对待。

### 会不会有 Web 面板被爆破的风险？

没有 Web 管理后台，这是刻意的取舍：默认单用户单节点，少一个暴露面。唯一对外的 HTTP 服务是订阅服务，而它只按 token 路径发静态文件。

---

## 许可与边界

### 开源协议是什么？能用在闭源商业项目里吗？

GPL-3.0。不能闭源分发；要么以 GPL-3.0 开源，要么和 sing-box 社区/作者协商商业许可。

### 它能绕过账号封禁、地区政策或协议检测吗？

不能，项目也不做这种承诺。它只负责把**你自己的服务器**配置成一个可用的代理出口。第三方服务是否接受某个出口 IP，取决于该服务自己的策略。

### 它能拿来做机场 / 卖节点吗？

不适合，也不在项目范围内。没有多用户、计费、到期管理和租户隔离；Web 面板、Docker/K8s、多用户计费都明确写在 [CONTRIBUTING.md](../../CONTRIBUTING.md) 的 out-of-scope 列表里。

### 怎么反馈问题或贡献代码？

Bug 和部署求助走 [Issues](https://github.com/qilaidev/anyreality-resi-stack/issues)（贴日志前记得脱敏 IP 和 token）。安全问题按 [SECURITY.md](../../SECURITY.md) 的流程私下上报。提 PR 前先读 [CONTRIBUTING.md](../../CONTRIBUTING.md)：`zh-CN` 是文档的事实来源，改了要同步 `docs/en/`，并且 `make test && make lint && make redact && make examples` 必须全绿。

---

## 相关文档

- [新手完整教程](BEGINNER_GUIDE.md) — 从买 VPS 到验证出口
- [部署指南](DEPLOYMENT.md) — 变量表、验证清单、升级、卸载
- [命令示例](EXAMPLES.md) — 常见场景的安装命令配方
- [分流规则](ROUTING.md) — 四层规则、增删域名、验证直连
- [双节点 + 智能分流](DUAL-NODE.md) — 住宅节点 + 数据中心备用节点
- [故障排查](TROUBLESHOOTING.md) — 连不上、卡片异常、流量漂移、锁服
- [客户端导入](CLIENTS.md) — 各平台客户端配置
- [同类评分对比](COMPARISON.md) — 和 3x-ui / x-ui / 手写配置怎么选
