# 新手完整教程

这篇教程面向第一次自己部署代理节点的人。你不需要先会写 sing-box / Xray 配置，只需要会登录 VPS，并愿意按步骤检查。

目标结果：

- 服务器上跑起 sing-box，默认同时开三条路径：VLESS + REALITY + Vision（TCP）、Hysteria2（UDP）、以及可选的 CDN 中转
- 本地客户端能通过订阅 URL 导入节点
- 浏览器出口 IP 是你的 VPS IP
- OpenAI / ChatGPT 链路可达
- 以后遇到 Telegram / Discord 慢时，知道什么时候该上双节点

## 1. 部署前准备

### VPS 怎么选

最低要求：

- Ubuntu 22.04+ / 24.04 LTS，或 Debian 12+
- 1 vCPU、512 MiB 内存、10 GiB 磁盘
- 公网 IPv4
- 可以开放 `443/tcp`
- 如果要使用订阅 URL，再开放 `80/tcp`

住宅 IP VPS 的价值在于：OpenAI、Anthropic、Netflix、银行等服务通常更信任这类出口。普通数据中心 VPS 也能部署，但就没有“住宅 IP 信誉”这个优势。

不建议新手一开始选择：

- CentOS 7、Alpine、OpenWRT
- Docker-only 或 Kubernetes-only 环境
- 只给 IPv6、没有公网 IPv4 的机器
- 不允许开 `443/tcp` 的机器

### 本地需要什么

你需要一台能 SSH 到服务器的电脑。macOS / Linux 可以直接用终端；Windows 可以用 PowerShell、Windows Terminal 或 Termius。

准备好这些信息：

```text
服务器 IP
root 用户或 sudo 用户
SSH 端口，通常是 22
```

## 2. SSH 登录服务器

用自己的服务器 IP 替换下面的例子：

```bash
ssh root@YOUR_SERVER_IP
```

如果你的 SSH 不是 22 端口：

```bash
ssh -p 2222 root@YOUR_SERVER_IP
```

登录后先确认系统：

```bash
cat /etc/os-release | head -5
```

看到 Ubuntu 22.04+、Ubuntu 24.04+ 或 Debian 12+ 就可以继续。

## 3. 先 dry-run，看脚本会做什么

强烈建议先 dry-run。dry-run 只打印将要执行的动作，不修改系统：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription \
  --dry-run
```

重点看输出里是否包含你预期的内容：

- 系统预检
- 安装 sing-box
- 生成 UUID / Reality key / Hysteria2 口令 / subscription token
- 配置 `443/tcp`
- 安装订阅服务到 `80/tcp`
- 配置 UFW / fail2ban
- 启用 systemd 服务

如果你不想安装订阅服务，可以去掉 `--with-subscription`，但新手推荐保留。订阅 URL 后续导入客户端更省事。

## 4. 正式安装

确认 dry-run 没问题后，去掉 `--dry-run`：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

默认安装即 **`vless-reality`（VLESS + REALITY + xtls-rprx-vision）**，无需额外参数。选它是因为它是唯一一个 sing-box 与 mihomo **都能写出来**的抗检测协议；论证见 [README 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。无需域名和证书。同时安装器还会默认开 Hysteria2（UDP）和备用端口，见 [国内网络优化](CHINA-NETWORK.md)。

如果你确定所有客户端都是 **sing-box 系**，可以改用 `--protocol anytls-reality` 换取更强的填充特性 —— 代价是**不生成 Clash 订阅**（mihomo 无法表达该节点）：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --protocol anytls-reality \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

安装完成后，终端会打印完成卡。你需要保存：

- 完成卡里的 `vless://...` 分享链接（只含直连 REALITY 一条路径）与 Hysteria2 口令；完整能力请用订阅 URL
- `Subscription URL: http://YOUR_SERVER_IP/YOUR_TOKEN`

不要把这些凭据发到公开 issue、论坛或截图里。它们包含你的节点凭据。

## 5. 在服务器上验证

先看 sing-box 是否在跑：

```bash
systemctl is-active sing-box
ss -tlnp | grep ':443'
sing-box check -C /etc/sing-box/conf
```

如果启用了订阅服务：

```bash
curl -i http://127.0.0.1/healthz
curl -I http://YOUR_SERVER_IP/$(grep ^SUB_TOKEN /etc/anyreality-resi-stack/secrets.env | cut -d= -f2)
```

`curl -I` 里应能看到：

- `Profile-Title`
- `Profile-Update-Interval`
- `Subscription-Userinfo`

## 6. 导入客户端

推荐优先使用订阅 URL，而不是手动粘贴凭据。以后改节点、换 IP、上双节点时，客户端刷新订阅即可同步。

订阅返回的格式由服务端按 User-Agent 决定，所以两个生态用**同一个 URL**：

- 全平台：sing-box 官方 App
- iOS / macOS / Android / Windows：Karing、Hiddify

sing-box 系（SFA / SFI / SFM、Karing、Hiddify、NekoBox）会拿到 `profile.json`；Clash 系（Clash Verge Rev、mihomo、Stash）会拿到 `profile.yaml`。想强制某个格式，就在 URL 后面直接写文件名，例如 `.../profile.yaml`：

- Windows：v2rayN
- macOS / Windows / Linux：Clash Verge Rev
- iOS / macOS：Stash
- iOS：Shadowrocket
- Android：v2rayNG / NekoBox

订阅 URL 本身不变，都是 `http://<server>/<TOKEN>/`。具体点击路径见 [客户端导入](CLIENTS.md)。

导入后请把客户端模式设为：

- sing-box / Karing / Hiddify：启动 VPN/TUN
- Clash Verge / Stash：`Rule`
- v2rayN：开启系统代理
- 移动端：启动 VPN/TUN

## 7. 验证出口 IP

打开浏览器访问：

```text
https://ipinfo.io
```

你应该看到服务器的公网 IP，而不是本地宽带 IP。

如果还是本地 IP，优先检查：

- 客户端是否真的启用了系统代理或 VPN
- 浏览器是否跟随系统代理
- 客户端是否选中了刚导入的节点
- Clash 类客户端是否处于 `Rule` 或 `Global`，不是 `Direct`

## 8. 验证 OpenAI / ChatGPT 链路

在本地终端通过客户端的本地代理端口测试：

```bash
curl --proxy socks5h://127.0.0.1:7891 -i https://api.openai.com/v1/models
```

正常情况下，没有 API key 会返回 `HTTP/2 401`。这代表 OpenAI 链路可达，只是请求未认证。

如果返回 `403 Country, region, or territory not supported`，说明这个出口 IP 被 OpenAI 拒绝。常见原因是：

- VPS IP 实际不是住宅 IP
- IP 所在地区不支持
- IP 段已经被服务方屏蔽

这不是安装脚本能修复的问题，需要换出口 IP 或供应商。

## 9. 什么时候需要双节点

单节点能跑通后，先用几天。只有出现这些情况时，再考虑双节点：

- Telegram 发图、发文件一直卡在“正在发送”
- Discord 语音卡顿，但网页浏览正常
- OpenAI / Claude 用住宅 IP 很顺，但即时通讯类应用明显慢

双节点的思路是：

- OpenAI / Claude / Netflix / banking 走住宅节点
- Telegram / Discord 走数据中心备用节点
- 客户端仍然只订阅一个 URL

部署方法见 [双节点 + 智能分流](DUAL-NODE.md)。

## 10. 常见坑

### 客户端连不上 / 不支持 Reality

默认协议 sing-box 系与 Clash 系都支持。只有 `--protocol anytls-reality` 是 sing-box 系专用 —— 那种模式下根本不会生成 Clash 订阅。

老版 Clash for Windows、ClashX 不支持 Reality，请换 Clash Verge Rev、Stash、v2rayN、v2rayNG、NekoBox 等维护中的客户端。

### 服务器防火墙没开端口

确认云厂商安全组和服务器 UFW 都允许 `443/tcp`。使用订阅服务时还要允许 `80/tcp`。

### 把凭据截图发出去了

如果泄露了 AnyTLS 密码、`vless://`、订阅 URL、UUID、Reality private key 或 token，最稳妥的做法是重新生成节点凭据，或重新部署。

### fail2ban 把自己锁了

先看 [故障排查](TROUBLESHOOTING.md) 的 fail2ban 小节。启用 `--harden-ssh` 前，请保留一个备用 SSH 会话，确认 key 登录可用后再继续。

## 下一步

- 想看完整安装参数：[部署指南](DEPLOYMENT.md)
- 想导入更多客户端：[客户端导入](CLIENTS.md)
- 想理解订阅和流量卡片：[订阅服务设计](SUBSCRIPTION.md)
- 想比较 3x-ui / x-ui / 手写配置：[同类评分对比](COMPARISON.md)
- 出问题先查：[故障排查](TROUBLESHOOTING.md)
