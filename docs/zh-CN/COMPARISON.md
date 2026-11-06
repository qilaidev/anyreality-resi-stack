# 同类评分对比

这不是“谁更高级”的通用排名，而是围绕一个具体场景评分：

> 已经有自己的 VPS，尤其是住宅 IP VPS；想部署自用的多路径 sing-box 节点（默认 **VLESS + REALITY + Vision**，另有 Hysteria2 与可选 CDN 中转）；希望新手能照文档落地；后续维护成本低；最好能处理 Telegram / Discord 对住宅 IP 软降权的问题。

如果你要做多用户商业面板、计费、到期管理，3x-ui / x-ui 这类项目会更合适。如果你只是要一个自用、可审计、低暴露面的住宅 IP 节点，`anyreality-resi-stack` 的取舍更直接。

> **上游跟进**：本页评分与推荐会随 sing-box / AnyTLS / REALITY 上游变更及时修订；安装器跟踪官方 apt 源，对比表随 release 同步（见仓库 [Changelog](../../CHANGELOG.md)）。
>
> **协议 vs 协议**（为什么默认不是 AnyReality）：[README · 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。**本页下面比的是部署栈 / 面板工具**，不是协议本身。

## 协议层速览（中国区自建 · 先选协议）

| 协议 | 客户端覆盖 | 在本仓库的位置 |
|---|---|---|
| **VLESS + REALITY + Vision** | **sing-box ＋ mihomo** | **默认主力路径** |
| AnyTLS + REALITY（AnyReality） | 仅 sing-box 系 | `--protocol anytls-reality`（填充更强，无 Clash 订阅） |
| Hysteria2 | sing-box ＋ mihomo | **默认第二条路径**（UDP，赛道不同，不替代 REALITY） |
| VLESS + WebSocket + CDN | sing-box ＋ mihomo | **可选第三条路径**，裸 IP 被封时唯一能通 |
| Trojan / 传统 TLS | 广 | 不做（强依赖域名证书，运维面更大） |
| Shadowsocks 2022 | 广 | 不做（TLS 层伪装与抗主动探测弱一档） |

完整论证：[README · 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。

## 部署栈总分

评分范围 1-5，分数越高表示越适合“住宅 IP 自托管 + 新手可落地 + 低维护 + 国内线路可用性”这个场景。

| 方案 | 总分 | 最适合的用户 | 核心取舍 |
|---|---:|---|---|
| anyreality-resi-stack | 4.8 | 自用住宅 IP / 小团队 / AI 工具用户 | 范围窄、三路径竞速、内嵌规则集防死锁、选择性 WARP 出站 + Watchdog、三态订阅自适应；不做多用户面板 |
| 233boy/sing-box · fscarmen/sing-box · mack-a | 3.9 | 需要在便宜机房 VPS 上用菜单快速切十几种协议的个人用户 | 协议菜单全、上手快；但以“单节点单路径 + 全局套 WARP”为主，无客户端多路径冷启动编排、无内嵌规则集防死锁、无住宅/机房双节点聚合 |
| 3x-ui | 3.8 | 需要 Web 面板、多协议、多用户管理的人 | 功能丰富，但面板和数据库带来更高运维面 |
| x-ui | 3.5 | 想用 Xray 面板快速管理多协议的人 | 面板能力强，自用住宅 IP 分流不是默认重点 |
| 手写 Xray/sing-box 配置 | 3.2 | 熟悉协议和配置的人 | 最灵活，但新手成本最高 |
| 商业机场/代理面板 | 2.8 | 不想自管服务器的人 | 省事，但不可审计，住宅 IP 出口不可控 |

## 维度评分

| 维度 | anyreality-resi-stack | 233boy / fscarmen / mack-a | 3x-ui | x-ui | 手写配置 | 商业服务 |
|---|---:|---:|---:|---:|---:|---:|
| 住宅 IP 场景适配（保原生 IP + 选择性 WARP） | 5 | 2 | 3 | 3 | 4 | 2 |
| 国内三网多路径防封（TCP+UDP+CDN+备用口） | 5 | 3 | 3 | 3 | 4 | 3 |
| 三态订阅自适应（sing-box + Clash + URI + 流量卡） | 5 | 2 | 4 | 4 | 1 | 4 |
| Telegram / Discord 分流 | 5 | 1 | 3 | 3 | 4 | 2 |
| 客户端启动期零网络防死锁（Inline Rule-Sets） | 5 | 1 | 2 | 2 | 3 | 2 |
| 安全默认值与结构不变量校验 | 5 | 3 | 3 | 3 | 2 | 2 |
| 可审计性 | 5 | 4 | 3 | 3 | 5 | 1 |
| 多用户 / 面板能力 | 1 | 2 | 5 | 5 | 2 | 4 |

## 为什么 anyreality-resi-stack 在这个场景更强

### 1. 它默认承认“住宅 IP 是资产”

很多通用安装器和面板默认服务的是“便宜 VPS 翻墙”场景，重点是多协议、多用户、面板管理。`anyreality-resi-stack` 的默认前提不同：住宅 IP 的价值在于出口信誉，所以应该优先给 OpenAI、Anthropic、Netflix、银行等服务使用。

### 2. 它把 Telegram / Discord 慢当成一等问题

住宅 IP 段可能被即时通讯服务软降权，常见表现是 Telegram 发文件卡死、Discord 语音质量差。本项目的双节点模式直接给出路径：OpenAI / Claude 走住宅节点，Telegram / Discord 走数据中心节点，客户端仍然只订阅一份配置。

### 3. 它没有 Web 面板暴露面

3x-ui / x-ui 的优势是 Web 管理和多用户能力，但 Web 面板也意味着额外登录入口、数据库、面板升级和访问控制。本项目默认通过 Bash + systemd + 文件配置完成部署，适合单用户和小团队自用。

### 4. 它更适合可重复部署

安装器支持 `--dry-run`、`--config`、`--non-interactive` 和幂等重跑。你可以先看它会做什么，再正式执行；也可以把变量放进配置文件，后续复制到新机器。

### 5. 它内置基础运维边界

默认处理 systemd 服务、UFW / fail2ban、BBR、swap、journald 限额、每日配置备份、`/healthz` 和 `Subscription-Userinfo`。这不是“更高级”，而是新手最容易漏掉的维护面。

### 6. 默认协议按「所有客户端内核都能表达」来选，并保留更强填充的选项

默认协议是 **VLESS + REALITY + Vision**（`--protocol vless-reality`）：它是唯一一个 sing-box 与 mihomo 都能写出来的抗检测协议，而「所有目标客户端内核都能表达」是本仓库选型的第一判据。`--protocol anytls-reality` 仍可选，填充更强，代价是不生成 Clash 订阅。协议层完整论证见 [README 协议选型](../../README.md#协议选型为什么默认不是-anyreality)；部署栈评分逻辑不受影响。

## 什么时候不该选它

不要为了所有场景都选 `anyreality-resi-stack`：

- 你要给很多用户开账号、限速、设置到期时间：选 3x-ui / x-ui。
- 你需要 Web UI 每天管理入站、出站和用户：选面板。
- 你想学习每一个 sing-box / Xray 字段：从官方文档和手写配置开始。
- 你不想维护服务器、不想碰 SSH：买商业服务更省事。
- 你需要 Kubernetes / Docker Compose / 多租户企业平台：这不是本项目范围。

## 依据与边界

对比依据来自公开项目说明和官方文档：

- [3x-ui README](https://github.com/MHSanaei/3x-ui)：Web-based Xray-core control panel、多协议、多用户、流量/到期/IP 限制、一行安装。
- [x-ui README](https://github.com/sing-web/x-ui)：Xray 面板、多协议、多入站/客户端、流量状态、订阅和 API 能力。
- [Project X 官方文档](https://xtls.github.io/)：VLESS、XTLS、REALITY 和 routing 是 Xray 生态的核心能力。
- [sing-box route 文档](https://sing-box.sagernet.org/configuration/route/)：route 规则支持按域名、IP、端口、协议等维度把连接送到不同 outbound。

这些来源只用于能力边界和场景对比。评分是面向本项目目标用户的产品判断，不代表通用技术优劣。

## 下一步

- 第一次部署：先看 [新手完整教程](BEGINNER_GUIDE.md)
- 已经会 SSH：直接看 [部署指南](DEPLOYMENT.md)
- 要导入客户端：看 [客户端导入](CLIENTS.md)
- TG / Discord 慢：看 [双节点 + 智能分流](DUAL-NODE.md)
