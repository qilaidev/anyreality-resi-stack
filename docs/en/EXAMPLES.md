# Usage examples

Install and operations command recipes for `anyreality-resi-stack`, organised by scenario. Every flag below exists in [`install/install.sh`](../../install/install.sh) — copy and run.

中文版: [docs/zh-CN/EXAMPLES.md](../zh-CN/EXAMPLES.md). Full variable list: [DEPLOYMENT.md](DEPLOYMENT.md#2-variables), or run `bash install/install.sh --help` on the server.

> Some commands below abbreviate the installer entry point as `bash <(curl -fsSL .../install.sh)`.
> The real URL is
> `https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh`,
> or `git clone` first and use `bash install/install.sh`.

---

## 1. Preview without changing anything (recommended first step)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --dry-run
```

`--dry-run` only prints the commands it would run: no files written, no packages installed, no firewall changes. Read the output, then drop the flag.

## 2. Minimal single-node install (default `vless-reality`)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

It finishes with a completion card: node name / protocol / IP / port / SNI, the per-path credentials, and the subscription URL. Both sing-box-family and Clash-family clients can import that URL directly.

## 3. Clash / mihomo clients: use legacy VLESS + Reality + Vision

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --protocol anytls-reality \
  --sni addons.mozilla.org \
  --with-subscription
```

AnyTLS padding is stronger, but mihomo cannot express the node, so **this command produces no Clash profile**. Use it only when every client is sing-box family.

## 4. Node only, no subscription server

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01"
```

Without `--with-subscription` nothing listens on `:80`, which keeps the exposed surface minimal. Read the client credentials back later:

```bash
grep -E '^(ANYTLS_PASSWORD|REALITY_PUBLIC_KEY|SHORT_ID)=' /etc/anyreality-resi-stack/secrets.env
```

## 5. Custom ports

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --inbound-port 8443 \
  --ssh-port 2222 \
  --with-subscription
```

`--inbound-port` changes the sing-box listen port (UFW rules, the rendered client profile, and uninstall cleanup all follow it). `--ssh-port` tells UFW which port to keep open so you do not lock yourself out. Keep 443 if you can — it is the least conspicuous.

## 6. Show a usage card (quota + provider reset day)

```bash
bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription \
  --total-bytes 1063004405760 \
  --billing-cycle-day 11 \
  --interface eth0
```

- `--total-bytes` — plan quota in bytes; `0` hides the quota. The value above is roughly 990 GiB.
- `--billing-cycle-day` — the provider's reset day, `1..28`; use `11` if your plan resets on the 11th.
- `--interface` — the NIC used for accounting; leave unset to auto-detect.

Accounting counts total NIC RX+TX; semantics in [SUBSCRIPTION.md](SUBSCRIPTION.md).

## 7. Pin versions for repeatable installs

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> \
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription \
  --singbox-version "<apt-package-version>"
```

- `ANYREALITY_RESI_STACK_REF` pins this repository's tag or branch (default `main`). Published tags: [Releases](https://github.com/qilaidev/anyreality-resi-stack/releases).
- `--singbox-version` pins the sing-box apt package version; if the repo does not carry it, the install fails instead of continuing with the wrong version.

## 8. Unattended / automated install (`--config` + `--non-interactive`)

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

The `--config` file is a plain `KEY=VALUE` file that gets sourced, so it can override any variable. Under `--non-interactive`, a missing required value is a hard error instead of a prompt. If public-IP detection fails, add `SERVER_IP=<your-public-ip>` to the same file.

## 9. Dual-node: residential leaf + data-center aggregator

**Step 1 — read the values off the already-installed residential node (leaf):**

```bash
grep -E '^(SUB_TOKEN|ANYTLS_PASSWORD|UUID|REALITY_PUBLIC_KEY|SHORT_ID)=' \
  /etc/anyreality-resi-stack/secrets.env
ip route get 1.1.1.1 | grep -oP 'src \K\S+'   # leaf public IP
```

Never copy `REALITY_PRIVATE_KEY` to the backup node.

**Step 2 — install the aggregator on the data-center VPS:**

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

`RESI_ANYTLS_PASSWORD` is required under `--protocol anytls-reality` (the default `vless-reality` authenticates with the UUID and does not need it). Missing required `RESI_*` variables abort the install rather than publishing a half-broken subscription. The DC node's own `DC_*` values default to this install's.

**Step 3 — clients subscribe to the aggregator URL only:**

```text
http://<DC_IP>/<AGGREGATOR_SUB_TOKEN>/
```

`--with-subscription` and `--with-aggregator` are mutually exclusive. Full background: [DUAL-NODE.md](DUAL-NODE.md).

## 10. Post-install verification

```bash
# Server side
systemctl status sing-box --no-pager
sing-box check -C /etc/sing-box/conf
curl -fsS http://<your-ip>/healthz
curl -sI http://<your-ip>/<SUB_TOKEN>/ | grep -i subscription-userinfo
journalctl -u sing-box -n 100 --no-pager

# Client side: the imported sing-box client opens a local mixed proxy on 2080
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com        # should print your VPS public IP
curl -x socks5h://127.0.0.1:2080 -s -o /dev/null -w '%{http_code}\n' https://chat.openai.com
```

Full checklist: [DEPLOYMENT.md](DEPLOYMENT.md#5-verification-checklist).

## 11. SSH hardening (off by default — handle with care)

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --harden-ssh --ssh-port 2222
```

`--harden-ssh` switches SSH to key-only and changes the port. **Confirm your public key is already on the server and keep a second SSH session open**, or you can lock yourself out. That risk is why it is off by default.

## 12. Uninstall

```bash
# Keep secrets and backups (default)
bash /opt/anyreality-resi-stack/install/uninstall.sh

# Purge one or the other
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-backups
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-secrets

# Purge everything (irreversible; all client subscriptions die immediately)
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-all
```

`bash install/install.sh --uninstall` hands off to the same script. Uninstalling does not remove the sing-box binary (apt-managed).

## 13. Local development and quality gates

```bash
git clone https://github.com/qilaidev/anyreality-resi-stack.git
cd anyreality-resi-stack

make test        # subscription server unit tests
make lint        # shellcheck + shfmt + ruff + yamllint + jsonlint
make redact      # scan the tree for leaked credentials
make mdcheck     # Markdown link check
make examples    # regenerate examples/ from templates/ (commit any diff)
```

Read [CONTRIBUTING.md](../../CONTRIBUTING.md) before touching the install scripts: `zh-CN` is the documentation source of truth and changes must be mirrored to `docs/en/`.

---

## Related documentation

- [Beginner guide](BEGINNER_GUIDE.md) · [Deployment](DEPLOYMENT.md) · [FAQ](FAQ.md)
- [Dual-node + smart routing](DUAL-NODE.md) · [Client routing rules](ROUTING.md)
- [Client import](CLIENTS.md) · [Troubleshooting](TROUBLESHOOTING.md)
- Placeholder sample configs: [`examples/`](../../examples) (RFC 5737 documentation IPs and sentinel values — not deployable)
