# FAQ | anyreality-resi-stack

**In one line:** open-source toolkit that deploys **sing-box AnyReality (AnyTLS+REALITY, default)** on a VPS you own via `install/install.sh`, with optional legacy VLESS+Vision, Python subscription servers, and dual-node routing — not an IP vendor or multi-user panel.

Runnable commands preferred. 中文版: [docs/zh-CN/FAQ.md](../zh-CN/FAQ.md). Landing FAQ: [README.en.md](../../README.en.md#faq).

- [What this project is](#what-this-project-is)
- [Protocols and clients](#protocols-and-clients)
- [Installation and deployment](#installation-and-deployment)
- [Subscription server](#subscription-server)
- [Routing and network behaviour](#routing-and-network-behaviour)
- [Dual-node](#dual-node)
- [Operations and security](#operations-and-security)
- [License and boundaries](#license-and-boundaries)

---

## What this project is

### What is anyreality-resi-stack?

An open-source (GPL-3.0) self-hosted proxy deployment toolkit. One Bash command installs a sing-box node on **your own** Ubuntu 22.04+ / Debian 12+ VPS, defaulting to **AnyReality (AnyTLS + REALITY)**, with an optional zero-dependency Python subscription server, usage-card headers, and dual-node domain routing. Entry point: [`install/install.sh`](../../install/install.sh).

### How is it different from 3x-ui / x-ui / XHTTP-Installer?

Those target "cheap VPS, many users, web panel, hide the exit IP". This project starts from the opposite premise: **your residential IP is an asset**. So it defaults to a single user, ships no web panel (one less attack surface), does not hide the exit IP, and only diverts the few services hostile to residential subnets. If you need multiple users, expiry dates, quotas, and an admin API, 3x-ui / x-ui fits better. Scored comparison: [COMPARISON.md](COMPARISON.md).

### Does it provide residential IPs or servers?

No. It is a **configuration tool**, not a resource provider. Bring your own VPS — residential-IP or ordinary data-center hosts both work.

### Who is it for?

Individual developers, small teams, AI-tool users, and multi-device users who own a VPS, are comfortable with SSH, and would rather not maintain a panel. First deployment: start with the [beginner guide](BEGINNER_GUIDE.md).

### What are the prerequisites?

An Ubuntu 22.04+ / 24.04 LTS or Debian 12+ VPS, root or sudo, SSH access, and a firewall / security group that allows `443/tcp` (plus `80/tcp` if you enable the subscription server). No domain, no TLS certificate, no Docker.

---

## Protocols and clients

### What is the default protocol, and how do I choose between AnyReality and VLESS+Reality?

The default is **VLESS + REALITY + xtls-rprx-vision** (`--protocol vless-reality`) — not because it
resists detection best, but because it is the only anti-detection protocol **both sing-box and
mihomo can express**.

**Why not AnyReality.** This repository used to default to it, and its padding really is stronger.
But mihomo's `anytls` block has no `reality-opts` field, so in a Clash profile that node **cannot be
written down at all** — while the server stayed green, `sing-box check` passed, and sing-box users
noticed nothing. **Only Clash users had no primary node, and what they saw was not an error.** It
took a month to find.

**Decision tree:**

1. Any Clash / mihomo / Stash client, or unsure → **keep the default `vless-reality`.**
2. Certain that every client is sing-box family and you want the stronger padding →
   `--protocol anytls-reality`, accepting that **no Clash profile is generated** (the installer says
   so explicitly).

```bash
# Only when you are certain no Clash client will ever be used
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" --protocol anytls-reality --with-subscription
```

Neither requires a domain or a certificate. Full argument:
[README protocol choice](../../README.en.md#protocol-choice-why-anyreality-is-no-longer-the-default).
Switching protocols means re-running the installer and **re-importing clients** (credential shape and
profile format both change).

### Which clients work?

Under the default protocol, **both ecosystems**: sing-box family (SFA / SFI / SFM, Karing, Hiddify,
NekoBox) and Clash family (Clash Verge, mihomo, Stash). There is one subscription URL and the server
picks `profile.json` or `profile.yaml` from the User-Agent. Only `--protocol anytls-reality` narrows
this to the sing-box family. Per-client steps: [CLIENTS.md](CLIENTS.md).

### Does Reality need a domain and a certificate?

No — that is its biggest advantage over Trojan / V2Ray-TLS. The default camouflage SNI is `addons.mozilla.org`; swap it with `--sni` for any real, reachable, high-reputation HTTPS site.

### Which fields do I need for a manual AnyReality import?

`type=anytls`, `server`, `port`, `password`, `tls.server_name=<SNI>`, `utls fingerprint=chrome`, `reality public_key`, `short_id`. They appear on the completion card and can be read back from the server:

```bash
grep -E '^(ANYTLS_PASSWORD|REALITY_PUBLIC_KEY|SHORT_ID)=' /etc/anyreality-resi-stack/secrets.env
```

### Where are the credentials stored after install?

`/etc/anyreality-resi-stack/secrets.env`, mode 600. The completion card prints once; the credentials themselves are not lost.

---

## Installation and deployment

### What is the one-line install command?

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

More recipes (custom port, pinned version, unattended, dual-node): [EXAMPLES.md](EXAMPLES.md).

### What does the installer actually do?

Preflight checks → BBR / swap / journald limits → sing-box from the official Sagernet apt repo (with a pinned GPG fingerprint) → generate UUID, Reality keypair, AnyTLS password, subscription token → render `/etc/sing-box/conf` → enable the systemd service → UFW + fail2ban → optional subscription server → daily config-backup timer → end-to-end self-check. Add `--dry-run` to see it without executing.

### Can I preview before it changes anything?

Yes, and you should the first time. `--dry-run` only prints the commands it would run:

```bash
bash <(curl -fsSL .../install.sh) --node-name "US-Resi-01" --dry-run
```

### Is the installer safe to re-run? Will it wipe my UUID and Reality keys?

It is **idempotent**. Re-running changes neither the UUID nor the Reality keypair; already-completed phases become no-ops. A daily systemd timer also backs the sing-box configuration up to `/var/backups/anyreality-resi-stack/` (last 3 archives retained).

### How do I pin a version for repeatable installs?

Pin this repository's tag or branch with `ANYREALITY_RESI_STACK_REF` instead of tracking `main`:

```bash
ANYREALITY_RESI_STACK_REF=<tag-or-branch> bash <(curl -fsSL .../install.sh) \
  --node-name "US-Resi-01" --with-subscription
```

To pin sing-box itself, add `--singbox-version <apt-package-version>`; if the apt repo does not carry that version the install fails outright rather than proceeding with the wrong one.

### How do I run it unattended?

Put every value in a `KEY=VALUE` file and pair it with `--non-interactive`:

```bash
bash <(curl -fsSL .../install.sh) --config /root/install.env --non-interactive
```

The variable list is in [DEPLOYMENT.md](DEPLOYMENT.md#2-variables). Without `--node-name`, non-interactive mode errors out instead of blocking on a prompt.

### Public IP auto-detection failed. Now what?

The installer auto-detects the public IP. If detection fails (outside `--dry-run`) it stops and tells you to set `SERVER_IP=<your-public-ip>` in the `--config` file. This is deliberate — otherwise the client profile would render with an unusable empty server field.

### Port 443 is taken. Can I change it?

Yes: `--inbound-port <N>`. UFW rules, the rendered client profile, and uninstall cleanup all follow that port. Still, 443 is the least conspicuous choice — keep it if you can.

### Are CentOS 7 / Alpine / OpenWRT / Docker / Kubernetes supported?

No, deliberately. BBR, journald limits, the sing-box apt repo, and GPG fingerprint verification all assume modern systemd + apt. A smaller compatibility matrix in exchange for stability. Docker / K8s support is explicitly out of scope in [CONTRIBUTING.md](../../CONTRIBUTING.md).

### I am upgrading from v1.x (reality-resi-stack). Anything to watch for?

Just re-run the installer. v2.0 unified runtime paths, systemd units, the backup script, and archives under the `anyreality-resi-stack` prefix, and the installer migrates the old `/etc/reality-resi-stack` and `/var/lib/reality-resi-stack` in place — **no loss of keys, state, or backups**. The legacy `REALITY_RESI_STACK_REF` environment variable is still honoured.

### How do I upgrade sing-box?

```bash
apt-get update && apt-get install --only-upgrade -y sing-box
systemctl restart sing-box
sing-box version
sing-box check -C /etc/sing-box/conf
```

### How do I uninstall?

```bash
bash /opt/anyreality-resi-stack/install/uninstall.sh
```

By default it **keeps** `/etc/anyreality-resi-stack/` (secrets) and `/var/backups/anyreality-resi-stack/` (archives). Use `--purge-all` to remove those too — irreversible, and every client subscription dies with it. The uninstaller does not remove the sing-box binary (apt-managed; `apt-get remove sing-box` if you want it gone).

---

## Subscription server

### What is the subscription server for? Is it required?

Not required. It is a zero-dependency Python HTTP service ([`subscription/leaf_server.py`](../../subscription/leaf_server.py)) that lets clients sync their configuration from one URL and renders a usage card via the `Subscription-Userinfo` header. Skip it and `scp` the client profile off the server manually instead. Design notes: [SUBSCRIPTION.md](SUBSCRIPTION.md).

### Is the subscription URL HTTPS? Can I share it?

**No — it is plain HTTP on `:80`**, and the profile it returns contains your node credential (the AnyReality password or the VLESS UUID). **Whoever has the URL has your node.** Never paste it into an issue, a screenshot, or a chat group. For encryption, front it with your own TLS reverse proxy, or fetch the profile once over `scp` and shut the subscription server down. Full write-up: [SECURITY.md](../../SECURITY.md#subscription-url-exposure--订阅地址的暴露面).

### I lost the subscription URL. How do I recover it?

```bash
grep ^SUB_TOKEN /etc/anyreality-resi-stack/secrets.env
# the URL is http://<your-public-ip>/<SUB_TOKEN>/
```

### The subscription loads but my client shows no usage card.

First confirm the service is up and the header is present:

```bash
curl -fsS http://<your-ip>/healthz
curl -sI http://<your-ip>/<SUB_TOKEN>/ | grep -i subscription-userinfo
```

If `total=0`, you installed without `--total-bytes`, so the card hides the quota. Step-by-step diagnosis: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### My usage numbers do not match my provider's dashboard.

This project counts **total NIC RX+TX**. Providers may count only egress, start the cycle on a different day, or measure at a different point, so short-term drift is expected. Align the reset day with `--billing-cycle-day` and backfill pre-install usage with `USAGE_OFFSET_BYTES`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Can I keep other files in the subscription directory?

**No.** Anything in `FILE_DIR` is downloadable through the same token path `/<TOKEN>/<filename>`. Never put backup archives or key material there.

---

## Routing and network behaviour

### I imported the subscription and now Chinese sites are slow. Is the node broken?

No. In TUN mode there is no "global / direct" switch — routing rules alone decide what gets proxied, and incomplete rules push domestic traffic overseas. The profile this project generates ships **four rule layers**: LAN-direct → ad-block → China domain/IP direct → proxy fallback, and works on import. If you hand-edited the config or used a template from elsewhere, check it against [ROUTING.md](ROUTING.md).

### Why is there an inline China domain list in addition to `geosite-cn`?

Because `geosite-cn` / `geoip-cn` rule sets are downloaded from GitHub, and if that download fails on first start the whole layer is lost and domestic traffic floods the node. This project therefore inlines a ~60-entry China-domain safety net ahead of it that needs no network request. See [ROUTING.md](ROUTING.md).

### Why does the default config block UDP 443 (QUIC / HTTP3)?

AnyTLS + Reality is TCP-only, so QUIC cannot traverse the node. Left unblocked, browsers keep retrying HTTP/3 and only fall back to TCP after a timeout — experienced as "pages hang for a few seconds first". Blocking `udp:443` makes the fallback **immediate**. Delete the rule if you do not want that; see [ROUTING.md](ROUTING.md).

### How do I add my own domains to the routing rules?

Add an entry to the `domain_suffix` array in the client profile, then validate and let clients refresh the subscription. If you edit the templates, regenerate `examples/` (the repo has a drift gate). Full steps: [ROUTING.md](ROUTING.md).

### How do I confirm a domain really goes direct?

Three ways: test while bypassing the environment proxy, raise the sing-box client log level to `info` and see which outbound the connection took, or just check the exit IP. Commands in [ROUTING.md](ROUTING.md).

### How do I verify the exit IP is my residential IP?

The imported sing-box client opens a local mixed proxy on `127.0.0.1:2080`:

```bash
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com
```

It should print your VPS public IP. If it does not, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Dual-node

### Telegram uploads stall on my residential VPS — "sending…" spins forever. What now?

Telegram soft-throttles residential subnets that have historically hosted bots. Enable **dual-node mode** and route `geosite:telegram` out through the data-center node. Rationale and deployment steps: [DUAL-NODE.md](DUAL-NODE.md).

### OpenAI says "unsupported region" on my data-center VPS, but the residential one makes Telegram slow. How do I get both?

That is exactly why this project exists: **OpenAI / Anthropic / banking / Netflix leave through the residential exit, Telegram / Discord leave through the data-center node**, and the client subscribes to a single URL whose profile carries both nodes plus the routing rules.

### How many servers does dual-node need? Is it mandatory?

Two (a residential leaf plus a data-center aggregator), and it is **not** mandatory. With one server — or if Telegram / Discord are fine for you — single-node `--with-subscription` is enough. Decision tree: [DUAL-NODE.md](DUAL-NODE.md).

### Do dual-node clients need two subscriptions?

No. Clients subscribe only to the aggregator URL; the single profile it returns already contains both nodes and the routing rules, with no extra client-side configuration.

### If the leaf goes offline briefly, does the usage card reset to zero?

No. The aggregator polls the leaf's `/<TOKEN>/status` in the background and caches the last good result, falling back to the cache when the leaf is unreachable — so you do not see a "0 used" jump. See [DUAL-NODE.md](DUAL-NODE.md).

---

## Operations and security

### How do I check service status and logs?

```bash
systemctl status sing-box --no-pager
journalctl -u sing-box -n 100 --no-pager
systemctl status subscription-leaf --no-pager    # or subscription-aggregator
curl -fsS http://<your-ip>/healthz
```

### Could my keys end up committed to Git?

Every server generates its own UUID / Reality keys / AnyTLS password / subscription token locally; real values never live in the repository. The repo ships a redaction scanner (`make redact`) and a hash-only denylist enforced in CI, and every value under `examples/` is an RFC 5737 documentation IP or a sentinel string that cannot be deployed.

### fail2ban locked me out. What do I do?

Log in from a different IP or via your provider's VNC / serial console, then unban. Commands in [TROUBLESHOOTING.md](TROUBLESHOOTING.md). This is also why `--harden-ssh` is off by default.

### I broke the config. How do I roll back?

The daily timer keeps backups in `/var/backups/anyreality-resi-stack/` (last 3 retained). Pick a recent archive and restore it — steps in [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Note that backups include `/etc/anyreality-resi-stack/` (credentials), so treat the archives as sensitive.

### Is there a web panel that could get brute-forced?

There is no web admin panel — a deliberate trade-off: single user, single node, one less exposed surface. The only public HTTP service is the subscription server, and it only serves static files under a token path.

---

## License and boundaries

### What is the license? Can I use it in a closed-source commercial project?

GPL-3.0. Not for closed-source distribution — either release under GPL-3.0 or negotiate commercial licensing with the sing-box community/authors.

### Can it bypass account bans, regional policy, or protocol detection?

No, and the project makes no such promise. It only configures **your own server** into a working proxy exit. Whether a third-party service accepts a given exit IP is that service's decision.

### Can I use it to run a paid proxy business?

It is not suitable and it is out of scope: no multi-user support, no billing, no expiry management, no tenant isolation. Web panels, Docker/K8s, and multi-user billing are all on the out-of-scope list in [CONTRIBUTING.md](../../CONTRIBUTING.md).

### How do I report a problem or contribute?

Bugs and deployment help go to [Issues](https://github.com/qilaidev/anyreality-resi-stack/issues) — redact IPs and tokens before pasting logs. Report security issues privately per [SECURITY.md](../../SECURITY.md). Before opening a PR, read [CONTRIBUTING.md](../../CONTRIBUTING.md): `zh-CN` is the documentation source of truth, changes must be mirrored to `docs/en/`, and `make test && make lint && make redact && make examples` must all pass.

---

## Related documentation

- [Beginner guide](BEGINNER_GUIDE.md) — from buying a VPS to verifying egress
- [Deployment](DEPLOYMENT.md) — variables, verification checklist, upgrade, uninstall
- [Usage examples](EXAMPLES.md) — install command recipes by scenario
- [Client routing rules](ROUTING.md) — the four layers, adding domains, verifying direct
- [Dual-node + smart routing](DUAL-NODE.md) — residential node plus data-center fallback
- [Troubleshooting](TROUBLESHOOTING.md) — connectivity, usage cards, counter drift, lockouts
- [Client import](CLIENTS.md) — per-platform client setup
- [Comparison](COMPARISON.md) — how to choose between this, 3x-ui, x-ui, and manual configs
