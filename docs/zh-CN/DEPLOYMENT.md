# 部署 | Deployment

本文档讲清楚从一台空白 Ubuntu/Debian VPS 到节点上线的完整流程。两种走法：

- **快速路径**：一行 `bash <(curl ...)` 调用 `install/install.sh`，由它自动完成全部步骤。适合 99% 的情况。
- **手动路径**：把 `install/lib/*.sh` 里的命令逐节贴在 shell 里执行。适合想理解每一步在做什么的人，或在受限网络里需要插队的人。

两种走法产出的服务器**完全等价**。

### 协议选择：vless-reality（默认）vs anytls-reality（可选）

安装器用 `--protocol` 开关（配置变量 `PROTOCOL`）在两种协议之间切换：

- **`--protocol vless-reality`（默认）**：VLESS + REALITY + `xtls-rprx-vision`，用 UUID + `flow` 认证。
  之所以是默认，不是因为它抗检测更强，而是因为它是**唯一一个 sing-box 与 mihomo 都能写出来**的
  抗检测协议。
- **`--protocol anytls-reality`（可选）**：AnyTLS + REALITY，简称 **AnyReality**。AnyTLS 的自定义填充
  让 TLS-in-TLS 更难被指纹识别 —— 这个优势是真实的。认证用每台服务器随机生成的**密码**
  （`ANYTLS_PASSWORD`），没有 UUID/flow。

> ⚠️ **选 `anytls-reality` 就没有 Clash 订阅。** mihomo 的 `anytls` 配置块没有 `reality-opts` 字段，
> `public-key` / `short-id` 无处可填，那个节点在 Clash YAML 里**根本写不出来**。
> `build_profile.py` 会**拒绝生成** YAML 而不是生成一份残缺的，安装器也会在完成卡上直接告诉你。
>
> 这条限制的代价本仓库付过：默认曾是 AnyReality，服务端全绿、`sing-box check` 通过、
> sing-box 用户一切正常，**只有 Clash 用户没有主力节点、而且看到的不是任何报错** ——
> 拖了一个月才定位。完整经过见 [README · 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。

`vless-vision` 是 `vless-reality` 的历史拼写，仍然被接受，指向同一个入站。

### 除了协议，还有两条路径默认/可选开启

协议只决定 TCP 那条路怎么握手。**在国内，单一路径必然会在某条线路上失效**，所以安装器还会：

| 路径 | 开关 | 默认 | 说明 |
|---|---|---|---|
| Hysteria2（UDP） | `--no-hysteria2` 关闭 | **开** | 自签名证书由安装器生成并**钉在订阅里**，不需要域名，也不放宽校验 |
| 备用端口 | `--alt-ports "2096,8880,40443"` / `--no-alt-ports` | **开** | iptables NAT REDIRECT 到主口，`sing-box` 配置零改动；**这些端口不会出现在 `ss -tlnp` 里** |
| CDN 中转（WS） | `--cdn-domain` + `--cdn-cert` + `--cdn-key` | 关 | 需自有域名与证书。**裸 IP 被整段黑洞的线路只有这条能通** |

为什么必须是三条、每条各自什么时候救命、以及实测数据，见
**[国内网络优化](CHINA-NETWORK.md)**。

**切换协议**：重跑安装器并改 `--protocol`（或配置文件里的 `PROTOCOL`）。安装器会替换入站文件、
避免双入站抢 443；**客户端必须重新导入**（凭据形态与订阅文件格式都会变）。

> **升级不会偷偷换掉你的协议。** 如果这台机上已经有 AnyReality 入站，而你重跑安装器时
> **没有**显式给 `--protocol`，安装器会保留 anytls-reality 并打印一条警告说明新默认值。
> 重跑安装器是文档规定的升级方式，它不能顺带把所有已导入的客户端弄失效。
> 真要切换就显式写 `--protocol vless-reality`，然后所有客户端重新导入。

---

## 1. 前置条件

### 服务器

- 系统：Ubuntu 22.04+ / 24.04 LTS，或 Debian 12+
- 权限：root 或 sudo
- 资源：1 vCPU、512 MiB 内存可跑（脚本会再加 2GiB swap）、10GiB 磁盘
- 网络：公网 IPv4，允许开放 `443/tcp`；若使用订阅服务，再开 `80/tcp`

### 本地

- 一台能 SSH 到服务器的机器

### 不需要的东西

- ❌ 域名
- ❌ TLS 证书（Reality 借用真实站点 SNI 握手）
- ❌ Vercel / Cloudflare 等第三方账号

---

## 2. 变量表

部署前先想清楚这些值。脚本支持交互式填空，但把所有值写进一个 `--config` 文件最干净：

| 变量 | 示例 | 说明 |
|---|---|---|
| `NODE_NAME` | `US-Resi-01` | 客户端显示名 |
| `PROTOCOL` | `vless-reality` | 协议：`vless-reality`（默认）或 `anytls-reality`（可选，无 Clash 订阅） |
| `ALT_PORTS` | `2096,8880,40443` | 备用端口（NAT REDIRECT 到主口）；`none` 关闭 |
| `WITH_HYSTERIA2` | `1` | 是否安装 Hysteria2（UDP）路径 |
| `HY2_PORT` | 同 `INBOUND_PORT` | Hysteria2 的 UDP 端口 |
| `CDN_DOMAIN` / `CDN_CERT` / `CDN_KEY` | 空 | 配齐则启用 CDN 中转路径 |
| `CDN_ORIGIN_PORT` | `8443` | CDN 回源端口，只能是 443/2053/2083/2087/2096/8443 |
| `CDN_IPS` | 一组分散网段的 CF 边缘 | 钉在订阅里的边缘 IP；按线路重选见 `scripts/pick-cf-ip.py` |
| `ALLOW_QUIC` | `0` | 置 1 则不拦客户端 udp/443 |
| `SNI` | `addons.mozilla.org` | Reality 伪装握手站，需真实可访问的 HTTPS 站 |
| `INBOUND_PORT` | `443` | sing-box 服务端口，强烈建议保持 443 |
| `SSH_PORT` | `22` | SSH 端口；若你改过，传入新值让 UFW 放行 |
| `INTERFACE` | `eth0` | 主网卡名，留空让脚本自动检测 |
| `TIMEZONE` | `America/Los_Angeles` | 可选 |
| `TOTAL_BYTES` | `1063004405760` | 套餐配额（字节），仅用于客户端流量卡片显示，留 0 隐藏 |
| `EXPIRE_TS` | `0` | 套餐到期 Unix 时间戳，`0` 表示不显示 |
| `BILLING_CYCLE_DAY` | `1` | 商家流量重置日；每月 11 号重置就填 `11` |
| `USAGE_POLL_INTERVAL_SECONDS` | `60` | 后台流量采样间隔 |
| `WITH_SUBSCRIPTION` | `1` | 是否安装订阅服务（推荐） |
| `WITH_AGGREGATOR` | `0` | 是否安装聚合模式（双节点才用） |
| `HARDEN_SSH` | `0` | 是否启用 SSH key-only + 改端口（默认关，避免锁服） |
| `SERVER_IP` | `203.0.113.10` | 写进客户端配置的服务器地址；留空则自动探测，探测失败时必须手动填 |
| `SINGBOX_VERSION` | 空 | 固定 sing-box 的 apt 包版本；留空取仓库最新稳定版 |
| `USAGE_OFFSET_BYTES` | `0` | 流量基线偏移（字节），用于补齐安装之前已经用掉的量，可为负 |
| `COUNT_CURRENT_BOOT_ON_INIT` | `true` | 首次建立统计状态时，是否把当前 boot 已累计的字节算进去 |

下面所有命令都假设你已经 `export` 了这些变量。命令行参数与变量一一对应（`--node-name` ↔ `NODE_NAME` …），完整参数清单可在服务器上跑 `bash install/install.sh --help`；按场景整理的命令配方见 [EXAMPLES.md](EXAMPLES.md)。

---

## 3. 快速路径：一行安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

脚本会自己 clone 仓库到 `/opt/anyreality-resi-stack/`，再 exec 完整安装器。所有阶段都在屏幕上有进度。默认协议是 `vless-reality`（两个客户端生态都支持）；确定不需要 Clash 时可加 `--protocol anytls-reality`。
真正改机器之前，安装器会先校验端口、流量数值、账期日、主机名、网卡名、布尔开关和用于渲染客户端配置的出口地址。
如果公网 IP 自动探测失败，请在 `--config` 文件里设置 `SERVER_IP`；否则客户端配置会被渲染成不可用的空 server。

默认拉取 `main`。如果你要固定某个分支或 tag，先到 [Releases](https://github.com/qilaidev/anyreality-resi-stack/releases) 选一个已发布 tag，再用：

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription
```

**强烈建议先跑一次 `--dry-run`**：

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --dry-run
```

`--dry-run` 模式下脚本只**打印**会执行的命令，不动任何系统状态。看一遍输出，确认你能接受每一步再去掉 `--dry-run`。

### 用 `--config` 文件（更适合自动化）

```bash
cat > /root/install.env <<'EOF'
NODE_NAME=US-Resi-01
PROTOCOL=anytls-reality
SNI=addons.mozilla.org
INBOUND_PORT=443
INTERFACE=eth0
TIMEZONE=America/Los_Angeles
TOTAL_BYTES=1063004405760
EXPIRE_TS=0
BILLING_CYCLE_DAY=1
USAGE_POLL_INTERVAL_SECONDS=60
WITH_SUBSCRIPTION=1
EOF

bash <(curl -fsSL .../install.sh) --config /root/install.env --non-interactive
```

---

## 4. 手动路径：按 phase 逐节执行

如果你想看每一步在做什么、或在自定义环境里只想跑某几个阶段，可以 clone 仓库后直接 source 库文件再调用对应 phase 函数：

```bash
git clone --depth 1 https://github.com/qilaidev/anyreality-resi-stack.git /opt/anyreality-resi-stack
cd /opt/anyreality-resi-stack
export REPO_ROOT="$PWD" COMMON_SH_LOADED=1
. install/lib/common.sh
. install/lib/system.sh
. install/lib/singbox.sh

export NODE_NAME=US-Resi-01 SNI=addons.mozilla.org INBOUND_PORT=443 INTERFACE=eth0

phase_preflight        # 系统检查
phase_system_init      # apt 包 + 内核调优（单文件 + 验生效值）+ swap + journald 限额
phase_install_singbox  # 安装 sing-box（含 GPG 指纹校验）
phase_migrate_legacy_paths  # 升级 v1.x：把 reality-resi-stack 目录/单元迁移到 anyreality-resi-stack
phase_generate_keys    # UUID / ANYTLS_PASSWORD + Reality 密钥对 + Hy2 口令与 obfs + WS 路径 + SUB_TOKEN
phase_configure_singbox  # 渲染 /etc/sing-box/conf/*（REALITY + Hysteria2 +（可选）VLESS-WS）
phase_singbox_service  # 写 systemd unit + enable --now
phase_firewall         # UFW（含 udp/<hy2>、回源端口只对 CDN 网段放行）+ fail2ban
phase_altports         # 备用端口 NAT REDIRECT（自有 iptables 链）
phase_cdn_relay        # 可选：nginx 回源 vhost + ws-ping-inject
phase_ops_tools        # 把 profile 构建器/校验器装到 /usr/local/lib
phase_subscription_*   # 写 params → 拉规则集 → 构建两种格式 → 校验 → 发布 → armed 周刷新
phase_verify           # 端到端自检（三条路径的监听与放行都查）
```

每个 phase 都是独立函数，幂等可重跑。源码在 `install/lib/`。

**从 v1.x（reality-resi-stack）升级**：直接重跑安装器即可。`phase_migrate_legacy_paths` 会自动把旧的 `/etc`、`/var/lib`、`/usr/local/lib`、`/var/backups` 下 `reality-resi-stack` 目录迁移到 `anyreality-resi-stack` 前缀，并退役旧的 `reality-resi-stack-backup` 单元，因此**沿用原有 UUID / Reality 密钥 / 密码，已导入的客户端无需重配**。

---

## 5. 验证清单

安装结束时脚本会打印一张"完成卡"：节点信息、各路径凭据、订阅 URL。最省事的复查是跑一次体检
（它覆盖三条路径、订阅结构不变量、规则集新鲜度、内核参数最终值）：

```bash
anyreality-resi-stack-healthcheck
```

想手动逐项看：

```bash
systemctl is-active sing-box                 # 应输出 active
ss -tlnp | grep ':443'                        # REALITY 监听
ss -ulnp | grep ':443'                        # Hysteria2 监听（UDP！）
ufw status | grep -E '443/(tcp|udp)'          # UDP 要单独放行，别只看 tcp
iptables -t nat -S ANYREALITY_ALTPORT         # 备用端口重定向（ss 里看不到它们）
sing-box check -C /etc/sing-box/conf          # 配置合法性
ufw status verbose                            # 防火墙规则
fail2ban-client status sshd                   # SSH 防爆破
sysctl net.ipv4.tcp_congestion_control        # 应输出 bbr
journalctl -u sing-box -n 20 --no-pager       # 启动日志无错误
```

订阅服务（若装了）：

```bash
curl -i http://127.0.0.1/healthz
curl -I http://YOUR_SERVER_IP/$(grep ^SUB_TOKEN /etc/anyreality-resi-stack/secrets.env | cut -d= -f2)
```

`curl -I` 应看到这几个响应头：

- `Content-Disposition`
- `Profile-Title`
- `Profile-Update-Interval`
- `Subscription-Userinfo`

订阅 URL 仍是 `http://<server>/<TOKEN>/`，**同一个 URL 同时服务两个生态** —— 服务端按 User-Agent
决定返回 sing-box `profile.json` 还是 Clash `profile.yaml`（明确指定文件名时以文件名为准）。
两份配置由同一个 `build_profile.py` 从同一份 params 生成，所以不会互相漂移。
`--protocol anytls-reality` 下只有 `profile.json`。流量卡片 / `Subscription-Userinfo` 行为不变。

客户端验证：

- 用订阅 URL 导入：sing-box 系（SFA/SFI/SFM、Karing、Hiddify、NekoBox）与 Clash 系
  （Clash Verge、mihomo、Stash）都可以，默认协议下两边都拿得到全部路径
- 访问 `https://api.openai.com/v1/models`，未带 API key 时应返回 401，证明 OpenAI 链路可达
- 用 `curl --proxy socks5h://127.0.0.1:7891 https://ipinfo.io` 确认出口 IP 是你的住宅 IP，不是别的

**AnyReality 手动导入所需凭据**（从完成卡或 `/etc/anyreality-resi-stack/secrets.env` 读取）：

- `type=anytls`
- `server` = 服务器地址，`port` = `INBOUND_PORT`
- `password` = `<ANYTLS_PASSWORD>`
- `tls.server_name` = `<SNI>`
- utls `fingerprint=chrome`
- reality `public_key` = `<REALITY_PUBLIC_KEY>`、`short_id` = `<SHORT_ID>`

注意 AnyReality **没有 `flow` 字段**。

---

## 6. 升级 sing-box 版本

```bash
apt-get update && apt-get install --only-upgrade -y sing-box
systemctl restart sing-box
sing-box version
sing-box check -C /etc/sing-box/conf
```

如果版本不在仓库锁定范围内（仓库 CI 会定期 bump），先看 [CHANGELOG.md](../../CHANGELOG.md) 确认兼容性。

如果新装时必须固定在某个已知 apt 包版本，可以传精确版本：

```bash
bash /opt/anyreality-resi-stack/install/install.sh \
  --node-name "US-Resi-01" \
  --with-subscription \
  --singbox-version "<apt-package-version>"
```

如果 Sagernet apt 仓库里没有这个版本，`apt-get` 会直接失败，不会继续启动 sing-box 服务。

---

## 7. 卸载

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh
```

默认保留 `/etc/anyreality-resi-stack/`（含密钥，不能公开传播）和 `/var/backups/anyreality-resi-stack/`（备份归档）。要全部清除：

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-all
```

⚠️ `--purge-all` 会删除认证凭据（UUID / `ANYTLS_PASSWORD` / Hysteria2 口令）和 Reality 密钥；删除后无法恢复，所有客户端订阅都将作废。

---

## 8. 下一步

- 第一次部署、想按步骤照做 → [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)
- 按场景查命令配方 → [EXAMPLES.md](EXAMPLES.md)
- 常见问题 → [FAQ.md](FAQ.md)
- 客户端怎么导入 → [CLIENTS.md](CLIENTS.md)
- 订阅服务的设计与端点契约 → [SUBSCRIPTION.md](SUBSCRIPTION.md)
- 启用双节点 + 智能分流（解决 TG 软风控等） → [DUAL-NODE.md](DUAL-NODE.md)
- 和 3x-ui / x-ui / 手写配置怎么选 → [COMPARISON.md](COMPARISON.md)
- 跑起来后出问题 → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
