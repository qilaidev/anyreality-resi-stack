# Deployment

This document walks you from a blank Ubuntu/Debian VPS to a running node. Two paths:

- **Fast path**: a single `bash <(curl ...)` line that runs `install/install.sh`. This is the right answer 99% of the time.
- **Manual path**: source the `install/lib/*.sh` modules and call phase functions yourself, one at a time. Useful if you want to understand each step or if you're working inside a restricted network where you need to interleave operations.

Both paths produce identical end states.

### Protocol choice: vless-reality (default) vs anytls-reality (opt-in)

The installer switches protocols with the `--protocol` flag (config variable `PROTOCOL`):

- **`--protocol vless-reality` (default)**: VLESS + REALITY + `xtls-rprx-vision`, authenticated with a
  UUID + `flow`. It is the default not because it resists detection better, but because it is the
  only anti-detection protocol **both sing-box and mihomo can express**.
- **`--protocol anytls-reality` (opt-in)**: AnyTLS + REALITY, or **AnyReality** for short. AnyTLS's
  custom padding genuinely does make TLS-in-TLS harder to fingerprint. Authentication uses a
  per-server random **password** (`ANYTLS_PASSWORD`) — there is no UUID/flow.

> ⚠️ **Choosing `anytls-reality` means no Clash profile at all.** mihomo's `anytls` block has no
> `reality-opts` field, so `public-key` / `short-id` have nowhere to go and the node **cannot be
> written into a Clash YAML profile**. `build_profile.py` **refuses to emit** YAML rather than
> emitting a crippled one, and the installer says so on the completion card.
>
> This repository has already paid for that constraint: AnyReality used to be the default, the
> server stayed green, `sing-box check` passed, sing-box users were fine — and **only Clash users had
> no primary node, with no error anywhere to tell them why.** It took a month to find. See
> [README · protocol choice](../../README.en.md#protocol-choice-why-anyreality-is-no-longer-the-default).

`vless-vision` is the historical spelling of `vless-reality` and still resolves to the same inbound.

### Two more paths, beyond the protocol

The protocol only decides how the TCP path performs its handshake. In China **a single path will
eventually fail on some line**, so the installer also sets up:

| Path | Flag | Default | Notes |
|---|---|---|---|
| Hysteria2 (UDP) | `--no-hysteria2` to disable | **on** | The installer mints a self-signed certificate and **pins it in the profile** — no domain needed, and verification is not weakened |
| Alternate ports | `--alt-ports "2096,8880,40443"` / `--no-alt-ports` | **on** | iptables NAT REDIRECT to the main port; zero sing-box config change. **These ports never show up in `ss -tlnp`** |
| CDN relay (WS) | `--cdn-domain` + `--cdn-cert` + `--cdn-key` | off | Needs your own domain and certificate. **The only path that works when the bare IP is blackholed** |

Why three, when each one saves you, and the measurements behind it:
**[Networks in China](CHINA-NETWORK.md)**.

**Switching protocols:** re-run the installer with a different `--protocol` (or `PROTOCOL` in the
config file). The installer replaces the inbound file and avoids two inbounds fighting over 443;
**clients must re-import** (credential shape and profile format both change).

> **An upgrade will not silently change your protocol.** If this host already has an AnyReality
> inbound and you re-run the installer **without** an explicit `--protocol`, it keeps
> `anytls-reality` and prints a warning explaining the new default. Re-running the installer is the
> documented way to update, so it must not also be a way to invalidate every client that already
> imported the AnyTLS password. Pass `--protocol vless-reality` deliberately to switch, then
> re-import on every client.

---

## 1. Prerequisites

### Server

- OS: Ubuntu 22.04 LTS or later, or Debian 12 or later
- Privileges: root or sudo
- Resources: 1 vCPU, 512 MiB RAM minimum (the installer adds 2 GiB swap), 10 GiB disk
- Network: public IPv4, ability to open `443/tcp`. If you enable the subscription server, also `80/tcp`.

### Local

- A machine that can SSH to the server.

### What you do **not** need

- ❌ A domain name
- ❌ A TLS certificate (Reality borrows the SNI handshake of a real public site)
- ❌ A Vercel / Cloudflare / third-party CDN account

---

## 2. Variables

Decide these before running. The installer prompts for missing values, but bundling everything into a `--config` file is cleanest:

| Variable | Example | Purpose |
|---|---|---|
| `NODE_NAME` | `US-Resi-01` | Display name shown in clients |
| `PROTOCOL` | `vless-reality` | Protocol: `vless-reality` (default) or `anytls-reality` (opt-in, no Clash profile) |
| `ALT_PORTS` | `2096,8880,40443` | Alternate ports (NAT REDIRECT to the main port); `none` disables |
| `WITH_HYSTERIA2` | `1` | Install the Hysteria2 (UDP) path |
| `HY2_PORT` | same as `INBOUND_PORT` | Hysteria2 UDP port |
| `CDN_DOMAIN` / `CDN_CERT` / `CDN_KEY` | empty | Set all three to enable the CDN relay path |
| `CDN_ORIGIN_PORT` | `8443` | Origin-pull port; only 443/2053/2083/2087/2096/8443 are accepted |
| `CDN_IPS` | a spread of CF edges | Edge IPs pinned in the profile; re-pick per line with `scripts/pick-cf-ip.py` |
| `ALLOW_QUIC` | `0` | Set to 1 to stop rejecting client udp/443 |
| `SNI` | `addons.mozilla.org` | Reality handshake server — must be a real, reachable HTTPS site |
| `INBOUND_PORT` | `443` | sing-box listen port; keep `443` unless you have a reason |
| `SSH_PORT` | `22` | SSH port (so UFW keeps it open if you've changed it) |
| `INTERFACE` | `eth0` | Primary NIC; leave empty for auto-detection |
| `TIMEZONE` | `America/Los_Angeles` | Optional |
| `TOTAL_BYTES` | `1063004405760` | Plan quota in bytes (for the client usage card only); `0` hides it |
| `EXPIRE_TS` | `0` | Plan expiry Unix timestamp; `0` hides it |
| `BILLING_CYCLE_DAY` | `1` | Provider traffic reset day; set `11` for plans that reset on the 11th |
| `USAGE_POLL_INTERVAL_SECONDS` | `60` | Background usage sampling interval |
| `WITH_SUBSCRIPTION` | `1` | Install the subscription server (recommended) |
| `WITH_AGGREGATOR` | `0` | Install in aggregator mode (dual-node only) |
| `HARDEN_SSH` | `0` | Apply SSH key-only + port change (off by default, to avoid lockouts) |
| `SERVER_IP` | `203.0.113.10` | Server address written into the client profile; auto-detected when empty, and required manually if detection fails |
| `SINGBOX_VERSION` | empty | Pin the sing-box apt package version; empty means the repo's latest stable |
| `USAGE_OFFSET_BYTES` | `0` | Accounting baseline offset in bytes — backfills usage from before the install; may be negative |
| `COUNT_CURRENT_BOOT_ON_INIT` | `true` | On first state creation, count bytes already accumulated in the current boot |

Every variable has a matching CLI flag (`--node-name` ↔ `NODE_NAME`, …); run `bash install/install.sh --help` on the server for the full list, and see [EXAMPLES.md](EXAMPLES.md) for scenario-based command recipes.

---

## 3. Fast path: one-line install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

The script clones the repo to `/opt/anyreality-resi-stack/` and execs the full installer. Every phase prints progress. The default protocol is `vless-reality`, which both client ecosystems support; append `--protocol anytls-reality` only when you are certain no Clash client is involved.
Before touching the machine, the installer validates ports, counters, billing
cycle day, hostnames, interface names, booleans, and the rendered profile host.
If public IP auto-detection fails, set `SERVER_IP` in `--config`; otherwise the
client profile would be rendered with an unusable empty server.

Remote-piped installs default to `main`. To pin a branch or tag, choose a published tag from [Releases](https://github.com/qilaidev/anyreality-resi-stack/releases), then run:

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --with-subscription
```

**Strongly recommended**: do a `--dry-run` first:

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --dry-run
```

In `--dry-run` mode the installer **prints** every command it would run but changes nothing. Read the output, satisfy yourself you can live with each step, then re-run without `--dry-run`.

### With a `--config` file (better for automation)

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

## 4. Manual path: phase-by-phase

If you want to see each step or run only a subset in a customized environment:

```bash
git clone --depth 1 https://github.com/qilaidev/anyreality-resi-stack.git /opt/anyreality-resi-stack
cd /opt/anyreality-resi-stack
export REPO_ROOT="$PWD" COMMON_SH_LOADED=1
. install/lib/common.sh
. install/lib/system.sh
. install/lib/singbox.sh

export NODE_NAME=US-Resi-01 SNI=addons.mozilla.org INBOUND_PORT=443 INTERFACE=eth0

phase_preflight        # OS / port / IPv4 / disk / RAM checks
phase_system_init      # apt deps + BBR + swap + journald limits
phase_install_singbox  # sing-box install with verified GPG fingerprint
phase_migrate_legacy_paths  # v1.x upgrade: move reality-resi-stack dirs/units to anyreality-resi-stack
phase_generate_keys    # UUID / ANYTLS_PASSWORD + Reality keypair + Hy2 password & obfs + WS path + SUB_TOKEN
phase_configure_singbox  # Render /etc/sing-box/conf/*
phase_singbox_service  # systemd unit + enable --now
phase_firewall         # UFW + fail2ban
phase_verify           # End-to-end checks
```

Each phase is an independent function and is idempotent. Source is `install/lib/`.

**Upgrading from v1.x (reality-resi-stack)**: just re-run the installer. `phase_migrate_legacy_paths` moves the old `reality-resi-stack` directories under `/etc`, `/var/lib`, `/usr/local/lib`, and `/var/backups` to the `anyreality-resi-stack` prefix and retires the old `reality-resi-stack-backup` unit, so your existing UUID / Reality keys / password are reused and **already-imported clients keep working**.

---

## 5. Verification checklist

When the installer finishes it prints a "completion card" with node details, per-path credentials and
the subscription URL. The quickest review is one health check — it covers all three paths, the
published profile's structural invariants, rule-set freshness and effective kernel parameters:

```bash
anyreality-resi-stack-healthcheck
```

To inspect it by hand — note the UDP listener and its **separate** firewall rule, because
`ufw allow 443` opens TCP only and a Hysteria2 inbound behind a TCP-only rule listens happily while
being unreachable from every client:

```bash
systemctl is-active sing-box                 # active
ss -tlnp | grep ':443'                       # REALITY listening
ss -ulnp | grep ':443'                       # Hysteria2 listening (UDP)
ufw status | grep -E '443/(tcp|udp)'         # both protocols must be allowed
iptables -t nat -S ANYREALITY_ALTPORT        # alternate ports (invisible to ss)
sing-box check -C /etc/sing-box/conf         # config validates
ufw status verbose                           # firewall rules
fail2ban-client status sshd                  # SSH jail
sysctl net.ipv4.tcp_congestion_control       # bbr
journalctl -u sing-box -n 20 --no-pager      # no errors on startup
```

Subscription server (if enabled):

```bash
curl -i http://127.0.0.1/healthz
curl -I http://YOUR_SERVER_IP/$(grep ^SUB_TOKEN /etc/anyreality-resi-stack/secrets.env | cut -d= -f2)
```

`curl -I` should show these response headers:

- `Content-Disposition`
- `Profile-Title`
- `Profile-Update-Interval`
- `Subscription-Userinfo`

The subscription URL is unchanged: `http://<server>/<TOKEN>/`, and **one URL now serves both ecosystems** — the server picks sing-box JSON or Clash YAML from the client's User-Agent (an explicit filename always wins). Both are generated by the same `build_profile.py` from the same params, so they cannot drift apart. Under `--protocol anytls-reality` only `profile.json` exists. For reference, `profile.json` (a complete sing-box client config — a `mixed` inbound on `127.0.0.1:2080`, an `anytls-reality` outbound, and `route.final` pointing at the node), while legacy VLESS-Vision serves `profile.yaml` (Clash). The usage card / `Subscription-Userinfo` behavior is unchanged.

Client-side:

- Import the subscription URL from either family: sing-box (SFA/SFI/SFM, Karing, Hiddify, NekoBox) or Clash (Clash Verge, mihomo, Stash). Under the default protocol both get every path.
- Hit `https://api.openai.com/v1/models` — without an API key, expect a 401, which means the OpenAI path is up
- `curl --proxy socks5h://127.0.0.1:7891 https://ipinfo.io` should report your residential IP

**Credentials for manual AnyReality import** (read from the completion card or `/etc/anyreality-resi-stack/secrets.env`):

- `type=anytls`
- `server` = your server address, `port` = `INBOUND_PORT`
- `password` = `<ANYTLS_PASSWORD>`
- `tls.server_name` = `<SNI>`
- utls `fingerprint=chrome`
- reality `public_key` = `<REALITY_PUBLIC_KEY>`, `short_id` = `<SHORT_ID>`

Note that AnyReality has **no `flow` field**.

---

## 6. Upgrading sing-box

```bash
apt-get update && apt-get install --only-upgrade -y sing-box
systemctl restart sing-box
sing-box version
sing-box check -C /etc/sing-box/conf
```

If you're jumping multiple major versions, check the upstream [sing-box release notes](https://github.com/SagerNet/sing-box/releases) for schema breakage. The CHANGELOG.md in this repo records compatibility-tested versions.

For new installs that must stay on a known package build, pass the exact apt
package version:

```bash
bash /opt/anyreality-resi-stack/install/install.sh \
  --node-name "US-Resi-01" \
  --with-subscription \
  --singbox-version "<apt-package-version>"
```

If the version is not available in the Sagernet apt repository, `apt-get`
fails before any sing-box service is started.

---

## 7. Uninstall

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh
```

By default this preserves `/etc/anyreality-resi-stack/` (including secrets; do not share it publicly) and `/var/backups/anyreality-resi-stack/`. To wipe everything:

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh --purge-all
```

⚠️ `--purge-all` deletes the auth credentials (UUID / `ANYTLS_PASSWORD` / Hysteria2 password) and the Reality keys; they cannot be recovered, and every client subscription becomes invalid.

---

## 8. Next

- First deployment, step by step → [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)
- Command recipes by scenario → [EXAMPLES.md](EXAMPLES.md)
- Common questions → [FAQ.md](FAQ.md)
- Importing into clients → [CLIENTS.md](CLIENTS.md)
- Subscription server design → [SUBSCRIPTION.md](SUBSCRIPTION.md)
- Enabling dual-node + smart routing (fixes Telegram soft-throttle, etc.) → [DUAL-NODE.md](DUAL-NODE.md)
- Choosing between this stack, 3x-ui, x-ui, and manual config → [COMPARISON.md](COMPARISON.md)
- Things go wrong → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
