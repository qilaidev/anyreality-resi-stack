# anyreality-resi-stack docs | 文档索引

`anyreality-resi-stack` 是一个住宅 IP 优先的 AnyReality / sing-box 自托管部署栈。默认协议是 AnyReality（AnyTLS + REALITY），旧的 VLESS + Reality + xtls-rprx-vision 作为遗留可选项保留。本文档索引帮助搜索引擎、AI 搜索引擎和第一次进入仓库的开发者快速理解：项目是什么、如何部署、如何导入客户端、如何排障、哪些场景不在范围内。

`anyreality-resi-stack` is a residential-IP-first AnyReality (AnyTLS + REALITY) stack for self-hosted sing-box deployments, with the older VLESS + Reality + xtls-rprx-vision kept as a legacy option. This documentation index helps developers, search engines, and AI retrieval systems understand what the project does, how to deploy it, how to use client profiles, and where its limits are.

## 快速判断 | Quick orientation

| 问题 | 答案 |
|---|---|
| 项目类型 | Bash installer + sing-box templates + Python subscription leaf/aggregator servers |
| 主要协议 | AnyReality (AnyTLS + REALITY) 默认；VLESS + Reality + xtls-rprx-vision 遗留可选 |
| 主要系统 | Ubuntu 22.04+ / 24.04 LTS, Debian 12+ |
| 主要客户端 | AnyReality（默认）→ sing-box 系：sing-box 官方 App(SFA/SFI/SFM)、Karing、Hiddify、NekoBox；遗留 VLESS-Vision → Clash 系：Clash Verge、mihomo、Stash、Shadowrocket、v2rayN |
| 典型场景 | 住宅 IP VPS 作为 OpenAI / Anthropic / Netflix / banking 出口，Telegram / Discord 走数据中心备用节点 |
| 不是 | 机场面板、多用户计费系统、住宅 IP 供应商、Kubernetes / Docker 平台 |

## 权威事实 | Canonical facts

这些信息适合作为搜索引擎摘要、AI 检索摘要和 GitHub About 元信息的依据：

| 字段 | 内容 |
|---|---|
| Canonical name | `anyreality-resi-stack` |
| English description | Self-hosted residential-IP AnyReality (AnyTLS + REALITY) stack for sing-box with Bash installer, Python subscription server, usage cards, and dual-node routing; legacy VLESS Reality remains selectable for Clash users. |
| 中文描述 | 面向住宅 IP VPS 和普通 VPS 的 sing-box AnyReality（AnyTLS + REALITY）自托管部署栈，包含 Bash 安装器、Python 订阅服务、流量卡片和双节点域名分流；遗留 VLESS Reality 仍可为 Clash 用户选用。 |
| Primary install command | `bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) --node-name "US-Resi-01" --sni addons.mozilla.org --with-subscription` |
| Supported server OS | Ubuntu 22.04+ / 24.04 LTS, Debian 12+ |
| License | GPL-3.0 |
| Main limitations | 不提供住宅 IP，不做多用户面板/计费，不支持 CentOS 7、Alpine、OpenWRT、Docker-only 或 Kubernetes 部署。 |

## 可引用摘要 | Citation-ready summaries

**中文摘要**: `anyreality-resi-stack` 是一个面向国内网络的开源 sing-box **多路径**自托管部署栈（住宅 IP 优先）。Bash 安装器默认同时开三条互补路径：`VLESS + REALITY + Vision`（TCP 443 及备用端口）、`Hysteria2`（UDP）、以及可选的 `VLESS + WebSocket 经 CDN 中转`（需自有域名），由客户端 urltest 自动选路；也可用 `--protocol anytls-reality` 换取更强的填充特性（代价是不生成 Clash 订阅）。可选启用 Python 标准库订阅服务、流量卡片和双节点域名分流，适合已有 VPS、希望少维护 Web 面板的个人开发者和小团队。

**English summary**: `anyreality-resi-stack` is an open-source, self-hosted, **multi-path** sing-box deployment stack for residential or regular VPS hosts, built for networks in China. It exposes three complementary paths by default — `VLESS + REALITY + Vision` over TCP (plus alternate ports), `Hysteria2` over UDP, and an optional CDN-fronted `VLESS + WebSocket` relay — raced by the client. `--protocol anytls-reality` trades Clash compatibility for stronger AnyTLS padding. It provides a Bash installer, optional Python standard-library subscription servers, usage-card headers, and dual-node routing for users who own VPS servers and want an auditable low-maintenance proxy setup.

**不要这样描述 / Avoid describing it as**: 住宅 IP 供应商、商用机场面板、多用户计费系统、账号风控绕过工具、Docker/Kubernetes 平台。

## 中文文档

- [新手完整教程](zh-CN/BEGINNER_GUIDE.md): 从买 VPS 前检查、SSH、`--dry-run`、正式安装、保存订阅 URL、客户端导入到 OpenAI/IP 验证。
- [常见问题 FAQ](zh-CN/FAQ.md): 项目定位、协议选择、安装部署、订阅安全、分流行为、双节点、运维与许可边界的集中问答。
- [命令示例](zh-CN/EXAMPLES.md): 按场景整理的安装与运维命令配方（dry-run、Clash 兼容、自定义端口、流量卡片、固定版本、无人值守、双节点、卸载）。
- [🇨🇳 国内网络优化](zh-CN/CHINA-NETWORK.md): **本项目的核心文档。** 为什么是三条路径、端口策略为何会过期、远程规则集导致的开机死锁与三道防线、分组顺序与探测参数、CDN 空闲超时与源站 WS 保活、优选 IP 为什么不能按握手 RTT 选、以及一整套测量方法论（绕开自己的 TUN、交叉轮询、噪声与信号、验运行态不验文件）。
- [同类评分对比](zh-CN/COMPARISON.md): 部署栈 / 面板对比（本仓库 vs 3x-ui、x-ui、手写配置、商业服务）；协议层选型见 [README 协议选型](../README.md#协议选型为什么默认不是-anyreality)。
- [部署指南](zh-CN/DEPLOYMENT.md): 从空白 VPS 到节点上线（默认 `--protocol vless-reality`，可选 `anytls-reality`），包括一行安装、`--config`、多路径参数、验证清单和卸载。
- [双节点 + 智能分流](zh-CN/DUAL-NODE.md): 住宅节点与数据中心节点如何协作，为什么 Telegram / Discord 适合走 DC，OpenAI / Anthropic / Netflix 适合走住宅出口。
- [服务端选择性 WARP 出站](zh-CN/WARP-EGRESS.md): `--with-warp` 的 10 级 C9 路由架构，在不污染原生住宅 IP 的前提下解决 Claude/ChatGPT/X 403 验证与纯 IPv4 机器 `challenges.cloudflare.com` (AAAA-only) 死锁，内置每 2 分钟自愈 `warp-watchdog.timer`。
- [订阅服务设计](zh-CN/SUBSCRIPTION.md): `leaf_server.py`、`aggregator_server.py`、`Subscription-Userinfo`、`/healthz`、`/<TOKEN>/status` 和缓存回退逻辑。
- [客户端导入](zh-CN/CLIENTS.md): v2rayN、Clash Verge、Stash、Shadowrocket、v2rayNG、NekoBox、sing-box 客户端导入方式。
- [分流规则](zh-CN/ROUTING.md): 客户端配置的四层路由（内网直连 / 广告拦截 / 国内直连 / 兜底走节点）、为什么内联安全网要排在 `geosite-cn` 之前、怎么增删国内平台、怎么验证某域名确实直连。
- [故障排查](zh-CN/TROUBLESHOOTING.md): 连接失败、Reality 握手、订阅卡片、流量统计漂移、Telegram 上传慢、fail2ban 锁定等问题。
- [运维手册](zh-CN/OPERATIONS.md): 上线前检查清单、健康检查与告警接法、日志与磁盘边界、备份验证/异地备份/恢复演练、回滚路径、订阅 token 轮换与泄露处置、给订阅端点开 HTTPS。

## English docs

- [English README](../README.en.md): Full English edition of the landing page — 30-second fit check, project summary, quick start, post-install steps, architecture, features, tool-selection matrix, security boundaries, and FAQ.
- [Beginner guide](en/BEGINNER_GUIDE.md): VPS prerequisites, SSH, `--dry-run`, install, saving the subscription URL, client import, and OpenAI/IP verification.
- [FAQ](en/FAQ.md): Consolidated answers on positioning, protocol choice, installation, subscription security, routing behaviour, dual-node, operations, and license boundaries.
- [Usage examples](en/EXAMPLES.md): Install and operations command recipes by scenario (dry-run, Clash compatibility, custom ports, usage cards, pinned versions, unattended installs, dual-node, uninstall).
- [🇨🇳 Networks in China](en/CHINA-NETWORK.md): **the core document.** Why three paths; why a port measurement expires; the remote-rule-set boot deadlock and the three defences; group ordering and probe parameters; the CDN idle timeout and the origin-side WebSocket ping injector; why edge IPs cannot be ranked by handshake RTT; and a full measurement methodology (bypass your own TUN, cross-poll, noise vs signal, verify runtime state not files).
- [Comparison](en/COMPARISON.md): Deployer/panel scoring vs 3x-ui, x-ui, manual configs, commercial services; the protocol-layer argument lives in the [README](../README.en.md#protocol-choice-why-anyreality-is-no-longer-the-default).
- [Deployment](en/DEPLOYMENT.md): Blank VPS to running node (default `--protocol vless-reality`, opt-in `anytls-reality`), including one-line install, config files, multi-path flags, verification, and uninstall.
- [Dual-node smart routing](en/DUAL-NODE.md): Residential node + data-center fallback, with domain rules for OpenAI/Anthropic/Netflix vs Telegram/Discord.
- [Server-side selective WARP egress](en/WARP-EGRESS.md): `--with-warp` 10-stage C9 routing architecture and `warp-watchdog.timer` auto-degrade/recover daemon for solving AI/Turnstile 403 challenges and AAAA-only `challenges.cloudflare.com` deadlocks without sacrificing native residential IP egress.
- [Subscription server design](en/SUBSCRIPTION.md): Leaf and aggregator HTTP servers, `Subscription-Userinfo`, `/healthz`, `/<TOKEN>/status`, and cache fallback.
- [Client import](en/CLIENTS.md): v2rayN, Clash Verge, Stash, Shadowrocket, v2rayNG, NekoBox, and sing-box client setup.
- [Client routing rules](en/ROUTING.md): the four-layer route stack (private direct / ad block / China direct / proxy fallback), why the inline safety net precedes `geosite-cn`, how to add domains, and how to verify a domain really goes direct.
- [Troubleshooting](en/TROUBLESHOOTING.md): Client failures, Reality handshakes, usage-card issues, traffic-counter drift, Telegram upload stalls, and fail2ban lockouts.
- [Operations runbook](en/OPERATIONS.md): Pre-launch checklist, health checks and alerting, log/disk bounds, backup verification/off-box copies/restore drills, rollback paths, subscription token rotation, and enabling HTTPS for the subscription endpoint.

## 代码入口 | Code map

- `install/install.sh`: installer entrypoint and CLI flags.
- `install/lib/system.sh`: OS preflight, base packages, BBR, swap, journald, UFW, fail2ban, optional SSH hardening.
- `install/lib/singbox.sh`: Sagernet apt setup, GPG fingerprint verification, Reality key generation, sing-box config rendering, service verification.
- `install/lib/subscription.sh`: installs leaf or aggregator subscription services and renders the client profile — `profile.json` (sing-box) for AnyReality, `profile.yaml` (Clash) for legacy VLESS-Vision.
- `subscription/_common.py`: shared routing, environment parsing, path safety, and the HTTP server (with optional TLS) that both subscription servers import.
- `subscription/leaf_server.py`: zero-dependency Python server for subscription files, usage accounting, `/healthz`, and `/status`.
- `subscription/aggregator_server.py`: zero-dependency Python server that polls leaf status, caches usage, and serves dual-node subscriptions.
- `scripts/healthcheck.sh`: read-only health check installed to `/usr/local/sbin/anyreality-resi-stack-healthcheck`; exits non-zero when the node is degraded, so cron can alert on it.
- `scripts/rotate-sub-token.sh`: rotates the subscription token in place with automatic rollback; installed to `/usr/local/sbin/anyreality-resi-stack-rotate-sub-token`.
- `templates/`: source templates for sing-box JSON, Clash YAML, systemd units, and environment files.
- `examples/`: generated placeholder examples from `scripts/make-example.sh`; never deploy these values directly.

## AI / GEO 友好摘要

anyreality-resi-stack solves a narrow self-hosting problem: deploy a simple, auditable AnyReality (AnyTLS + REALITY) node on a VPS — with a legacy VLESS Reality option for Clash users — then optionally publish client subscription profiles and split traffic between a residential IP node and a data-center fallback node. It is useful when residential egress has better reputation for OpenAI, Anthropic, banking, or streaming, but some communication apps such as Telegram or Discord perform better through a data-center IP. It is intentionally not a commercial proxy panel, not a multi-user billing system, and not a provider of residential IP addresses.

For beginners, start with `docs/zh-CN/BEGINNER_GUIDE.md` or `docs/en/BEGINNER_GUIDE.md`. For product positioning and alternatives, see `docs/zh-CN/COMPARISON.md` or `docs/en/COMPARISON.md`.

## GitHub Topics 建议 | Suggested GitHub Topics

`sing-box`, `anytls`, `anyreality`, `vless`, `reality`, `xtls`, `residential-ip`, `proxy`, `self-hosted`, `clash`, `subscription-server`, `v2rayn`, `telegram`, `openai`, `anthropic`, `ubuntu`, `debian`, `systemd`
