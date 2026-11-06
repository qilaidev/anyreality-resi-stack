# 运维手册 | Operations

面向"已经装好、要长期跑下去"的节点。上线前照着第 1 节走一遍，之后主要用第 2 节的健康检查和第 4 节的恢复演练。

安装器会把两个运维工具装到服务器上，所以出事的时候不需要手边有仓库：

| 命令 | 作用 |
|---|---|
| `/usr/local/sbin/anyreality-resi-stack-healthcheck` | 只读健康检查，任何时候都能跑，不改任何东西 |
| `/usr/local/sbin/anyreality-resi-stack-rotate-sub-token` | 轮换订阅 token（订阅 URL 泄露时的止损手段） |

第 1–6 节是日常运维，第 7 节是给订阅端点开 HTTPS，第 8 节列出这套东西刻意不做的事。

---

## 1. 上线前检查清单

装完之后、把订阅 URL 发给任何人之前，逐条确认：

```bash
# 一次性把绝大多数问题查出来
anyreality-resi-stack-healthcheck
```

它必须全绿。除此之外还要人工确认：

- [ ] **已经保存好凭据**。`/etc/anyreality-resi-stack/secrets.env`（mode 600）里的 `ANYTLS_PASSWORD` / `UUID` 和 Reality 密钥对丢了就只能重装，所有客户端订阅作废。离线抄一份。
- [ ] **另开一个 SSH 会话验证过还能登录**，尤其是用了 `--harden-ssh` 或改过 `--ssh-port` 之后。UFW 已经开了 sshd 实际监听的端口，但仍然要亲自验证一次。
- [ ] **真实客户端连通**：至少一台设备导入订阅、走节点访问 `https://ipinfo.io`，确认出口 IP 是预期的住宅 IP。服务端的 `phase_verify` 只能证明本机 TLS 握手正常，证明不了链路可用。
- [ ] **订阅 URL 按密码对待**。明文 HTTP 下，链路上的人能直接读到 profile 里的节点密码。有域名就按第 7 节开 TLS；无论如何都别把 URL 贴进聊天群、issue、截图。
- [ ] **`FILE_DIR`（`/etc/anyreality-resi-stack/files`）里只有 profile 文件**。这个目录下的任何文件都会在同一个 token 路径下被公开，不要往里面放备份或笔记。
- [ ] **确认时钟同步**：`timedatectl show -p NTPSynchronized --value` 必须是 `yes`。时钟偏移过大时 Reality 握手会失败，表现和"被封"一模一样。
- [ ] **确认磁盘有余量**：`df -h /`。低于 20% 空闲就先清理再上线。

---

## 2. 日常健康检查与告警

```bash
anyreality-resi-stack-healthcheck          # 人读的完整报告
anyreality-resi-stack-healthcheck --quiet  # 只在有问题时输出（给 cron 用）
```

退出码：`0` 健康（可能带 warning），`1` 至少一项 FAIL，说明节点已经降级或挂了。

检查覆盖：sing-box 服务状态与重启次数、配置是否还能通过 `sing-box check`、入站端口是否在监听、订阅服务与 `/healthz`（开了 TLS 会自动走 HTTPS）、TLS 证书是否临近过期、profile 文件是否存在、备份是否新鲜且没失败、是否配了异地备份钩子、根分区占用、`box.log` 体积、时钟同步、UFW 状态、`secrets.env` 权限。

**接告警最省事的方式**是 cron：cron 只要有输出就发邮件，而 `--quiet` 在健康时完全不输出。

```bash
sudo crontab -e
# 加一行：
*/10 * * * * /usr/local/sbin/anyreality-resi-stack-healthcheck --quiet
```

要推到手机（Telegram / Bark / 企业微信等）就把它包一层：

```bash
sudo tee /usr/local/sbin/anyreality-alert.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
out="$(/usr/local/sbin/anyreality-resi-stack-healthcheck --quiet 2>&1)" && exit 0
curl -fsS --max-time 10 -X POST \
  "https://api.telegram.org/bot<BOT_TOKEN>/sendMessage" \
  -d chat_id="<CHAT_ID>" \
  --data-urlencode "text=[$(hostname)] anyreality 健康检查失败:
$out" >/dev/null
EOF
sudo chmod 700 /usr/local/sbin/anyreality-alert.sh
```

然后把 crontab 里那行换成 `anyreality-alert.sh`。

### 手动排查常用命令

```bash
systemctl status sing-box
journalctl -u sing-box -n 100 --no-pager
journalctl -u subscription-leaf -n 100 --no-pager
sing-box check -C /etc/sing-box/conf
ss -tlnp | grep sing-box
```

---

## 3. 日志与磁盘

日志有三处，都已经封顶，但值得知道边界在哪：

| 来源 | 位置 | 上限 |
|---|---|---|
| systemd journal | journald | `SystemMaxUse=100M`，保留 14 天（`/etc/systemd/journald.conf.d/99-limits.conf`） |
| sing-box | `/etc/sing-box/logs/box.log` | logrotate 每天轮转、单文件超过 20 MiB 立即轮转、保留 7 份压缩（`/etc/logrotate.d/sing-box`） |
| 订阅服务 | 走 journald | 同上 |

sing-box 默认 `level=error`，正常情况下 `box.log` 几乎不长。如果健康检查开始 warn 它的体积，说明有东西在持续报错，去看日志内容而不是只删文件。

手动验证轮转策略：

```bash
sudo logrotate -d /etc/logrotate.d/sing-box   # dry-run，不实际轮转
```

---

## 4. 备份、验证与恢复演练

备份由 `anyreality-resi-stack-backup.timer` 每天跑一次，产物在 `/var/backups/anyreality-resi-stack/`，只保留最近 3 份。

归档**包含**：`/etc/sing-box`（不含 `logs/`）、三个 systemd unit、`/etc/anyreality-resi-stack`（含密钥和 token）、`/usr/local/lib/anyreality-resi-stack`、`/var/lib/anyreality-resi-stack`、`/etc/ufw`、`/etc/fail2ban`、`/etc/sysctl.d`、journald 配置。
**不包含**：`usage-state.json` / `usage-cache.json`（运行态计数）、sing-box 日志。

备份脚本在写完之后会自检：归档必须能被 `tar -tzf` 列出，并且必须真的含有 `etc/sing-box/conf/` 和 `etc/anyreality-resi-stack/`；任何一项不满足就删掉这份坏归档并以非零码退出（健康检查会因此报 FAIL）。这样不会出现"轮转掉了好备份、留下一份打不开的"。

> ⚠️ 归档里有密钥和 token，权限是 600，不要公开传播。

### 异地备份（强烈建议配）

备份和系统在同一块盘上——**VPS 整机没了备份也没了**。安装器会建好钩子目录，放一个可执行脚本进去即可，备份成功后会带着归档路径调用它：

```bash
sudo cp /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh.example \
        /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh
sudo nano /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh   # 填 rclone / scp 目标
sudo chmod +x /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh

# 立刻验证一次，不用等到第二天
sudo systemctl start anyreality-resi-stack-backup.service
sudo journalctl -u anyreality-resi-stack-backup.service -n 30 --no-pager
```

钩子失败会让整个备份任务以非零码退出，健康检查随即报 FAIL —— 这是刻意的：**你以为存在、实际不存在的异地副本**才是最危险的情况。本地归档不会因为钩子失败被删掉。

没配钩子时健康检查会给一条 warning 提醒你。归档里有密钥，异地目标要私有且静态加密。

### 恢复演练（建议上线后做一次）

```bash
# 1. 看有哪些备份
ls -lh /var/backups/anyreality-resi-stack/

# 2. 先验证归档可读、内容齐全（不解压到系统）
ARCHIVE=/var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz
tar -tzf "$ARCHIVE" | head -20
tar -tzf "$ARCHIVE" | grep -c '^etc/anyreality-resi-stack/'

# 3. 解到临时目录看一眼内容对不对（安全，不影响运行中的系统）
mkdir -p /tmp/restore-drill && tar -xzf "$ARCHIVE" -C /tmp/restore-drill
cat /tmp/restore-drill/manifest.txt
rm -rf /tmp/restore-drill
```

### 真正恢复

```bash
systemctl stop sing-box subscription-leaf 2>/dev/null || true
tar -xzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz -C /
systemctl daemon-reload
sing-box check -C /etc/sing-box/conf      # 先验证配置，再起服务
systemctl start sing-box
systemctl start subscription-leaf 2>/dev/null || true
anyreality-resi-stack-healthcheck
```

恢复后流量计数会从恢复时刻重新起算（运行态没进归档）。要对齐服务商面板，用 `USAGE_OFFSET_BYTES` 补一个偏移，见[故障排查 → 流量统计漂移](TROUBLESHOOTING.md)。

---

## 5. 回滚

| 场景 | 做法 |
|---|---|
| 改配置改坏了 | 用第 4 节的备份归档恢复 `/etc/sing-box` |
| 新版本 sing-box 有问题 | `apt-get install sing-box=<旧版本>` 后 `systemctl restart sing-box`；可用版本看 `apt-cache madison sing-box` |
| 换协议后客户端连不上 | 重跑安装器并带上原来的 `--protocol`；`secrets.env` 会被复用，密钥不会重新生成 |
| 想整体退回干净状态 | `bash install/install.sh --uninstall`（默认保留密钥和备份） |

重跑安装器是安全的：它是幂等的，已存在的 `secrets.env` 会被复用而不是重新生成——这一点很关键，重新生成密钥等于让所有已导入的客户端全部作废。

---

## 6. 订阅 token 轮换（泄露处置）

订阅 URL 就是凭据。截图外发、客户端把 profile 同步给了第三方、电脑丢了，都按泄露处理。

```bash
sudo anyreality-resi-stack-rotate-sub-token --dry-run   # 先看会改什么
sudo anyreality-resi-stack-rotate-sub-token
```

脚本会改写 `secrets.env` 里的 `SUB_TOKEN` 和订阅服务 env 里的 `TOKEN`，重启服务，并验证 `/healthz` 和新路径确实能取到 profile；起不来就自动回滚到旧 token。

轮换之后：

1. **所有客户端都要重新导入新 URL**，旧 URL 直接 404。
2. 如果有另一台机器跑 aggregator 指向本机，记得同步更新它的 `REMOTE_STATUS_URL`，否则它的流量卡片会停在缓存值上。
3. 如果泄露的不只是 URL，而是节点密码本身（`ANYTLS_PASSWORD`），轮换 token 不够——需要删掉 `secrets.env` 后重跑安装器，代价是全部客户端重新导入。

---

## 7. 给订阅端点开 HTTPS（有域名就该开）

默认订阅走明文 HTTP :80，链路上的任何人都能看到 token 和 profile 里的节点密码。**有域名就应该开 TLS**，订阅服务内置支持（Python 标准库，零额外依赖）：

```bash
# 1. 域名解析到本机，用 certbot 签一张证书（80 端口签发时先停订阅服务）
sudo systemctl stop subscription-leaf
sudo certbot certonly --standalone -d sub.example.com

# 2. 重跑安装器，带上证书路径。secrets.env 会被复用，密钥不变
sudo bash install/install.sh --node-name "US-Resi-01" --with-subscription \
  --sub-tls-cert /etc/letsencrypt/live/sub.example.com/fullchain.pem \
  --sub-tls-key  /etc/letsencrypt/live/sub.example.com/privkey.pem
```

安装器会把证书和私钥的属组授权给非特权的 `anyreality-sub` 用户，并在 env 文件里写入 `TLS_CERT_FILE` / `TLS_KEY_FILE`。开启后：

- 订阅 URL 变成 `https://sub.example.com/<TOKEN>/` —— **必须用签发证书的那个域名，不能用 IP**。
- 健康检查会自动改用 HTTPS 探测，并额外检查证书是否在 7 天内过期（证书过期是典型的"静默故障"：客户端全部拒绝，而探活还是绿的）。
- certbot 续期后要 `systemctl restart subscription-leaf` 才会加载新证书。加一条 deploy hook：

```bash
echo 'systemctl restart subscription-leaf' | \
  sudo tee /etc/letsencrypt/renewal-hooks/deploy/restart-subscription.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-subscription.sh
```

没有域名就只能保持 HTTP，把订阅 URL 当密码管，并在怀疑泄露时用第 6 节轮换。

---

## 8. 已知边界

这些是设计取舍，不是待修的 bug，但上线前应该知道：

- **没有域名时订阅只能走明文 HTTP**。有域名见第 7 节。
- **流量统计是网卡口径**，统计的是整机 `rx+tx`，包含系统更新等非代理流量，只能近似服务商面板。
- **单机、无 HA**。sing-box 挂了由 systemd 无限重启（`StartLimitIntervalSec=0`，不会因为反复失败被永久停住），但机器没了就是没了。
- **单用户**。没有多用户、没有计费、没有面板。

订阅服务以非特权用户 `anyreality-sub` 运行，只有 `CAP_NET_BIND_SERVICE`（用于绑 :80）。systemd 在降权**之前**以 root 读取 EnvironmentFile，所以 `secrets.env` 保持 0600 root 独占，HTTP 服务本身读不到它。

---

## 相关文档

- [部署指南](DEPLOYMENT.md)：从空白 VPS 到节点上线。
- [故障排查](TROUBLESHOOTING.md)：连接失败、Reality 握手、流量漂移等具体症状。
- [订阅服务设计](SUBSCRIPTION.md)：leaf / aggregator 的接口与缓存行为。
