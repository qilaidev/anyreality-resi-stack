# 命令示例 | Usage examples

`anyreality-resi-stack` 的可复制安装/运维配方（Quick Start 之外的场景）。每条参数均对应真实入口 [`install/install.sh`](../../install/install.sh)。

English: [docs/en/EXAMPLES.md](../en/EXAMPLES.md)。变量表：[DEPLOYMENT.md](DEPLOYMENT.md#2-变量表)；或 `bash install/install.sh --help`。

> 下文为了不刷屏，部分命令把安装入口缩写成 `bash <(curl -fsSL .../install.sh)`。实际执行时请用完整地址：
> `https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh`，
> 或者先 `git clone` 再用 `bash install/install.sh`。

---

## 1. 先预览，不改动任何东西（推荐第一步）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --dry-run
```

`--dry-run` 只打印将要执行的命令，不写任何文件、不装任何包、不动防火墙。看完输出确认可以接受，再去掉这个参数。

## 2. 最小单节点安装（默认协议 `vless-reality`）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

装完打印一张完成卡：节点名 / 协议 / IP / 端口 / SNI、各路径凭据、订阅 URL `http://<IP>/<SUB_TOKEN>`。sing-box 系与 Clash 系客户端都可以直接导入这个 URL。

## 3. Clash / mihomo 客户端：改用遗留 VLESS + Reality + Vision

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --protocol anytls-reality \
  --sni addons.mozilla.org \
  --with-subscription
```

`anytls-reality` 的 AnyTLS 填充更强，但 mihomo 无法表达该节点，因此**这条命令不会生成 Clash 订阅**。只有确定所有客户端都是 sing-box 系时才用它。

## 4. 不装订阅服务，只要一个节点

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01"
```

不加 `--with-subscription` 就不开 `:80`，暴露面最小。之后手动取客户端凭据：

```bash
grep -E '^(ANYTLS_PASSWORD|REALITY_PUBLIC_KEY|SHORT_ID)=' /etc/anyreality-resi-stack/secrets.env
```

## 5. 自定义端口

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --inbound-port 8443 \
  --ssh-port 2222 \
  --with-subscription
```

`--inbound-port` 改 sing-box 监听端口（UFW 规则、客户端配置、卸载清理都会跟着走）。`--ssh-port` 告诉 UFW 你的 SSH 端口，避免放行规则漏掉它导致锁服。能不换 443 就不换 —— 它最不显眼。

## 6. 显示流量卡片（配额 + 商家账期日）

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription \
  --total-bytes 1063004405760 \
  --billing-cycle-day 11 \
  --interface eth0
```

- `--total-bytes`：套餐配额（字节），`0` = 隐藏配额。上例约等于 990 GiB。
- `--billing-cycle-day`：商家流量重置日，取值 `1..28`；每月 11 号重置就填 `11`。
- `--interface`：统计用的网卡，留空自动探测。

统计口径是网卡 RX+TX 总量，语义见 [SUBSCRIPTION.md](SUBSCRIPTION.md#流量统计的语义)。

## 7. 固定版本，做可重复部署

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> \
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription \
  --singbox-version "<apt-package-version>"
```

- `ANYREALITY_RESI_STACK_REF` 固定本仓库的 tag / 分支（默认 `main`）。已发布 tag 见 [Releases](https://github.com/qilaidev/anyreality-resi-stack/releases)。
- `--singbox-version` 固定 sing-box 的 apt 包版本；apt 源里没有该版本时安装直接失败，不会带着错版本继续。

## 8. 无人值守 / 自动化安装（`--config` + `--non-interactive`）

```bash
cat > /root/install.env <<'EOF'
NODE_NAME=US-Resi-01
PROTOCOL=anytls-reality
SNI=addons.mozilla.org
INBOUND_PORT=443
SSH_PORT=22
INTERFACE=eth0
TIMEZONE=America/Los_Angeles
TOTAL_BYTES=1063004405760
EXPIRE_TS=0
BILLING_CYCLE_DAY=1
USAGE_POLL_INTERVAL_SECONDS=60
WITH_SUBSCRIPTION=1
EOF
chmod 600 /root/install.env

bash <(curl -fsSL .../install.sh) --config /root/install.env --non-interactive
```

`--config` 文件就是一份被 `source` 的 `KEY=VALUE`，能覆盖任何变量。`--non-interactive` 下缺少必填项会直接报错，而不是卡在提示符上。公网 IP 自动探测失败时，在这个文件里补 `SERVER_IP=<你的公网IP>`。

## 9. 双节点：住宅 leaf + 数据中心 aggregator

**第 1 步 — 在已装好的住宅节点（leaf）上取值：**

```bash
grep -E '^(SUB_TOKEN|ANYTLS_PASSWORD|UUID|REALITY_PUBLIC_KEY|SHORT_ID)=' \
  /etc/anyreality-resi-stack/secrets.env
ip route get 1.1.1.1 | grep -oP 'src \K\S+'   # leaf 公网 IP
```

不要把 `REALITY_PRIVATE_KEY` 复制到备用节点。

**第 2 步 — 在数据中心 VPS 上装 aggregator：**

```bash
cat > /root/aggregator.env <<'EOF'
RESI_SERVER_IP=<LEAF_IP>
RESI_UUID=<LEAF_UUID>
RESI_REALITY_PUBLIC_KEY=<LEAF_REALITY_PUBLIC_KEY>
RESI_ANYTLS_PASSWORD=<LEAF_ANYTLS_PASSWORD>
RESI_NODE_NAME=US-Resi-01
RESI_SNI=addons.mozilla.org
RESI_INBOUND_PORT=443
EOF
chmod 600 /root/aggregator.env

bash <(curl -fsSL .../install.sh) \
  --config /root/aggregator.env \
  --node-name "US-DC-01" \
  --sni addons.mozilla.org \
  --with-aggregator "http://<LEAF_IP>/<LEAF_SUB_TOKEN>/status"
```

`--protocol anytls-reality` 下 `RESI_ANYTLS_PASSWORD` 是必填的（默认的 `vless-reality` 用 UUID 认证，不需要它）。缺少必填的 `RESI_*` 变量时安装器会直接停止，避免生成半坏的订阅。数据中心节点自身的 `DC_*` 值默认由本次安装派生。

**第 3 步 — 客户端只订阅 aggregator 的 URL：**

```text
http://<DC_IP>/<AGGREGATOR_SUB_TOKEN>/
```

`--with-subscription` 和 `--with-aggregator` 互斥。完整背景见 [DUAL-NODE.md](DUAL-NODE.md)。

## 10. 装完之后的验证命令

```bash
# 服务器侧
systemctl status sing-box --no-pager
sing-box check -C /etc/sing-box/conf
curl -fsS http://<your-ip>/healthz
curl -sI http://<your-ip>/<SUB_TOKEN>/ | grep -i subscription-userinfo
journalctl -u sing-box -n 100 --no-pager

# 客户端侧：导入的 sing-box 客户端默认在本地 2080 起混合代理
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com        # 应返回你 VPS 的公网 IP
curl -x socks5h://127.0.0.1:2080 -s -o /dev/null -w '%{http_code}\n' https://chat.openai.com
```

完整验证清单见 [DEPLOYMENT.md](DEPLOYMENT.md#5-验证清单)。

## 11. SSH 加固（默认关闭，谨慎使用）

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --harden-ssh --ssh-port 2222
```

`--harden-ssh` 会启用 key-only 登录并改端口。**先确认你的公钥已经在服务器上、并且另开一个 SSH 会话保持连接**，否则容易把自己锁在外面。默认关闭就是这个原因。

## 12. 卸载

```bash
# 保留密钥和备份（默认）
bash /opt/anyreality-resi-stack/install/uninstall.sh

# 只清备份 / 只清密钥
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-backups
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-secrets

# 全部清除（不可恢复，所有客户端订阅立即作废）
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-all
```

也可以用 `bash install/install.sh --uninstall` 转交给同一个脚本。卸载不会移除 sing-box 二进制（由 apt 管理）。

## 13. 本地开发与质量门禁

```bash
git clone https://github.com/qilaidev/anyreality-resi-stack.git
cd anyreality-resi-stack

make test        # 订阅服务单元测试
make lint        # shellcheck + shfmt + ruff + yamllint + jsonlint
make redact      # 扫描是否有凭据泄漏
make mdcheck     # Markdown 链接检查
make examples    # 从 templates/ 重新生成 examples/（有 diff 就要提交）
```

改动安装脚本前先读 [CONTRIBUTING.md](../../CONTRIBUTING.md)：`zh-CN` 是文档事实来源，改了要同步 `docs/en/`。

---

## 相关文档

- [新手完整教程](BEGINNER_GUIDE.md) · [部署指南](DEPLOYMENT.md) · [常见问题 FAQ](FAQ.md)
- [双节点 + 智能分流](DUAL-NODE.md) · [分流规则](ROUTING.md)
- [客户端导入](CLIENTS.md) · [故障排查](TROUBLESHOOTING.md)
- 占位值样例配置：[`examples/`](../../examples)（RFC 5737 文档 IP + 哨兵值，不可直接部署）
