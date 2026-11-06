# anyreality-resi-stack

**Self-hosted, multi-path sing-box stack built for networks in China (residential-IP first)**

`anyreality-resi-stack` (formerly `reality-resi-stack`) is an open-source (GPL-3.0), auditable **Bash one-line installer** that deploys **sing-box** on **Ubuntu 22.04+ / Debian 12+**, exposing three complementary paths by default — **VLESS + REALITY + Vision (TCP)**, **Hysteria2 (UDP)**, and **VLESS + WebSocket behind a CDN** (optional, needs a domain) — raced by the client. Plus a zero-dependency Python subscription server, usage cards, and dual-node domain routing. Entry point: [`install/install.sh`](install/install.sh).

> **Why three paths instead of one:** a single path will eventually fail on some line, and **when it does the server shows nothing wrong**. The three failure causes are uncorrelated. Full reasoning, measurements and method: **[Networks in China](docs/en/CHINA-NETWORK.md)** — the core document of this project.

It is **not** a residential-IP vendor, multi-user panel, or commercial proxy marketplace. You bring the VPS; this repo configures it.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Ubuntu 22.04+](https://img.shields.io/badge/Ubuntu-22.04%2B-orange.svg)](docs/en/DEPLOYMENT.md)
[![sing-box](https://img.shields.io/badge/core-sing--box-purple.svg)](https://sing-box.sagernet.org)
[![protocol](https://img.shields.io/badge/protocol-VLESS%2BReality%20%7C%20Hysteria2%20%7C%20WS%2BCDN-green.svg)](docs/en/CHINA-NETWORK.md)
[![Release](https://img.shields.io/github/v/release/qilaidev/anyreality-resi-stack)](https://github.com/qilaidev/anyreality-resi-stack/releases)

[简体中文 README](README.md) · [Beginner guide](docs/en/BEGINNER_GUIDE.md) · [Examples](docs/en/EXAMPLES.md) · [FAQ](docs/en/FAQ.md) · [Deployment](docs/en/DEPLOYMENT.md) · [Clients](docs/en/CLIENTS.md) · [Routing](docs/en/ROUTING.md) · [Comparison](docs/en/COMPARISON.md) · [llms.txt](llms.txt) · [Changelog](CHANGELOG.md)

> English edition. The [Chinese README](README.md) is authoritative and updated first; `docs/en/` mirrors `docs/zh-CN/`.

## What / why / who

| | |
| --- | --- |
| **What** | Self-hosted proxy **deployment stack**: installer + sing-box templates + Python subscription servers + docs |
| **Problem** | Configure your residential or DC VPS as an importable node; optional dual-node sends OpenAI-class traffic via residential egress and Telegram/Discord via a DC fallback |
| **Who** | People who own a VPS, use SSH, and prefer Bash+systemd over a web panel |
| **Default protocol** | **VLESS + REALITY + Vision** — the only anti-detection protocol *every* client kernel can express; see [protocol choice](#protocol-choice-why-anyreality-is-no-longer-the-default) |
| **Censorship resistance** | Three paths (TCP / UDP / CDN) plus alternate ports, raced by the client's url-test |
| **Stack** | Bash, sing-box, AnyTLS, REALITY, VLESS/Vision (legacy), Python stdlib HTTP, systemd, UFW, fail2ban |
| **OS** | Ubuntu 22.04+ / 24.04 LTS, Debian 12+ |
| **Paths** | `install/install.sh`; runtime `/etc/sing-box/conf`, `/etc/anyreality-resi-stack/` |

**Two things first:** ① client profiles ship China-direct / ad-block / LAN-direct rules for TUN ([routing](docs/en/ROUTING.md)); ② subscription is **plain HTTP :80** and contains the node password — **the URL is a credential** ([SECURITY.md](SECURITY.md#subscription-url-exposure--订阅地址的暴露面)).

## Quick start

```bash
# Preview only
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" --sni addons.mozilla.org --with-subscription --dry-run

# Install (default: vless-reality + Hysteria2 + alternate ports)
bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription
```

What it does: preflight + kernel tuning/swap → sing-box from official apt (GPG-pinned) → keys and per-path credentials → REALITY inbound on `:443` plus a Hysteria2 inbound on `udp:443` (self-signed cert, pinned in the profile) → alternate-port NAT redirects → systemd / UFW / fail2ban → optional CDN relay (nginx + WebSocket keepalive injector) → fetch and **inline** the rule-sets, generate both profile formats, validate them → self-check.

Add the CDN relay path (the only way out when the bare IP is blackholed):

```bash
... --cdn-domain relay.example.com --cdn-cert /path/fullchain.pem --cdn-key /path/key.pem
```

| Need | How |
| --- | --- |
| Pin version | `ANYREALITY_RESI_STACK_REF=<tag>` |
| Unattended | `--config FILE --non-interactive` |
| First time | [Beginner guide](docs/en/BEGINNER_GUIDE.md) |
| More recipes | [Examples](docs/en/EXAMPLES.md) |

Import the completion-card subscription URL with a **sing-box client** (SFA/SFI/SFM, Karing, Hiddify, NekoBox), then:

```bash
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com
curl -fsS http://<your-ip>/healthz
systemctl status sing-box --no-pager
```

## Core features

- One-line install: `install/install.sh` (`--dry-run` / `--non-interactive` / `--config` / idempotent)
- Three complementary paths: REALITY (TCP) + Hysteria2 (UDP) + VLESS+WS via CDN (optional), auto-raced
- Alternate ports 2096/8880/40443 as NAT REDIRECTs to the main port — **zero sing-box config change**
- All rule-sets inlined: **no network at client startup**, which removes the boot deadlock entirely
- Optional AnyReality: `--protocol anytls-reality` — stronger padding, at the cost of no Clash profile
- Three-ecosystem adaptive subscription: `subscription/leaf_server.py` serves `profile.json` (sing-box), `profile.yaml` (Clash/mihomo with `packet-encoding: xudp`), or `profile.txt` (Base64 multi-path URI bundle for Shadowrocket / v2rayN / v2rayNG / Streisand) from a single `/<TOKEN>/` URL via User-Agent detection or `?format=singbox|clash|uris`, plus `/status`, `/healthz`, and usage cards
- Server-side selective WARP egress: `--with-warp` ([WARP-EGRESS](docs/en/WARP-EGRESS.md)) attaches a native sing-box WireGuard endpoint (`warp-ep`) with 10-stage C9 route invariants and a 2-minute auto-degrade/recover watchdog (`warp-watchdog.timer`), routing only Turnstile/403-challenged AI/social domains and the AAAA-only `challenges.cloudflare.com` widget via WARP while keeping Google/Netflix/TikTok/banking on your native residential IP
- Ready-made routing: LAN direct → ad block → China direct (inline safety net + 175 domestic suffixes + geosite/geoip) → reject UDP/443 → proxy
- Dual-node: residential for OpenAI/Anthropic/Netflix; DC for Telegram/Discord ([DUAL-NODE](docs/en/DUAL-NODE.md))
- Ops defaults: systemd, UFW (with pinned Cloudflare IPv4/IPv6 origin-pull fallback), fail2ban, BBR + UDP/QUIC socket buffer tuning & GRO/GSO offload, dual-stack `iptables`/`ip6tables` port redirects, swap, backup timer, and deep health checks (including C3 drift and C9 WARP audits)
- Safety: per-host secrets; redact + hash denylist in CI

## Use cases

| Scenario | Recommendation |
| --- | --- |
| Residential VPS for ChatGPT / Claude / banking / streaming reputation | This stack, single node + subscription |
| Residential works for AI but TG/Discord uploads stall | [Dual-node](docs/en/DUAL-NODE.md) |
| Single-user, no panel, auditable | This stack |
| Multi-user billing / web admin API | 3x-ui / x-ui |
| Must use Clash/mihomo | The default already works — no extra flag |
| Shadowrocket / v2rayN / v2rayNG | Same subscription URL auto-serves Base64 multi-path URIs (or append `?format=uris`) |
| Claude/ChatGPT/X 403 challenge or IPv4-only Turnstile deadlock | Add `--with-warp` for [selective server-side WARP egress](docs/en/WARP-EGRESS.md) |
| Bare IP unreachable (China Mobile / Broadcast-TV) | Add `--cdn-domain` for the CDN relay path |

Deployer comparison: [COMPARISON](docs/en/COMPARISON.md). Protocol comparison: next section.

## Limits

- Does **not** sell VPS/IPs; no multi-user billing, airport panel, K8s/Docker-only/OpenWRT/CentOS 7
- Does **not** claim to bypass account risk controls, regional policy, or protocol blocking
- `--protocol anytls-reality` is **unsupported** by mihomo/most Clash (the installer refuses to emit a Clash profile rather than emitting a broken one); **never share** the subscription URL
- The CDN relay path needs **your own domain, certificate and CDN account** — not provided here
- Former name `reality-resi-stack` (v1.x) redirects here; runtime prefix is `anyreality-resi-stack`

**Suggested GitHub About:** `Multi-path self-hosted sing-box stack for networks in China — REALITY + Hysteria2 + CDN relay, Bash installer, Python subscription, dual-node routing.`  
**Suggested topics:** `sing-box` `anytls` `anyreality` `reality` `vless` `residential-ip` `proxy` `self-hosted` `subscription-server` `ubuntu` `debian` `systemd` `openai` `telegram`

AI summary: [llms.txt](llms.txt) · Docs index: [docs/README.md](docs/README.md)

## Why this exists

Most VLESS installers target cheap-VPS bypass. **Residential VPS is the opposite:** you paid for egress reputation (OpenAI, banking, Netflix), yet the same subnet may be soft-throttled by Telegram or Discord. This project treats the residential IP as an asset and routes hostile services around it. Dual-node steps: [DUAL-NODE.md](docs/en/DUAL-NODE.md).

## After install

Completion card: node info, per-path credentials (the `vless://` share link, the Hysteria2 password), subscription `http://<IP>/<SUB_TOKEN>/`. **Prefer the subscription, not the bare `vless://`** — the share link describes only the direct REALITY path and carries no Hysteria2, no CDN relay, no alternate ports, no automatic failover and no routing rules. Samples under `examples/`. Manual fields and clients: [CLIENTS.md](docs/en/CLIENTS.md). Verify with the `curl` commands above. Troubleshooting: [TROUBLESHOOTING.md](docs/en/TROUBLESHOOTING.md).

## Protocol choice: why AnyReality is no longer the default

> **The first question when choosing a protocol is not "which is fastest" but
> "can every client kernel I need to support express this node?"** This project
> asked them in the wrong order and paid a month for it.

### What happened

This repository used to default to **AnyTLS + REALITY**, and the argument was
sound: custom padding suppresses TLS-in-TLS characteristics, REALITY supplies
server camouflage, no domain or certificate is needed, and it measured better
than Trojan on weak links. **The conclusion was still wrong.**

The reasoning was fine. The mistake was looking only at the server and never at
client kernel coverage:

> mihomo's `anytls` block has **no `reality-opts` field**, so there is nowhere
> to put `public-key` / `short-id`
> ([docs](https://wiki.metacubex.one/en/config/proxies/anytls/) ·
> [issue #2155](https://github.com/MetaCubeX/mihomo/issues/2155)).
> In a Clash-family subscription **the primary node cannot be written down at
> all.**

The shape is worth memorising: server entirely green, `sing-box check` passing,
sing-box users perfectly fine — and **only Clash users with no primary node,
seeing "a few nodes missing from the list" rather than any error.** Nothing on
the server side indicated a problem, which is why it took a month to find.

### The default today

| | Default | Opt-in |
|---|---|---|
| **Protocol** | `--protocol vless-reality` (VLESS + REALITY + xtls-rprx-vision) | `--protocol anytls-reality` |
| **Client coverage** | sing-box family ✅ · Clash / mihomo ✅ | sing-box family ✅ · Clash / mihomo ❌ |
| **Anti-detection** | REALITY server camouflage, no domain or cert | REALITY + AnyTLS padding (the padding really is stronger) |
| **Subscription output** | `profile.json` + `profile.yaml` | **`profile.json` only** |

AnyReality's padding is a genuine advantage and it has not been removed. But
choosing it means **no Clash profile** — the installer says so and
`build_profile.py` refuses to emit YAML rather than emitting a crippled one.
That is deliberate: silently leaving half your users without a node is far worse
than a loud error.

### 30-second decision tree

```text
Is any of my clients Clash / mihomo / Stash?
  ├─ Yes (or not sure) → vless-reality (the default; leave it)
  └─ All sing-box family, and certain no Clash client will be added
        → anytls-reality is available, for stronger padding
           Cost: JSON-only subscription; adding one Clash user later means reinstalling

Lossy link, UDP passes?             → the Hysteria2 path is on by default
Bare IP blackholed (Mobile/BTV)?    → the CDN relay path is required; see CHINA-NETWORK.md
Already have domain + cert + proxy? → Trojan/TLS works, heavier to run; out of scope here
```

### Protocol comparison

Scenario fixed as: **China-based users · self-hosted node · anti-detection
required · minimal domain/certificate overhead.** This is a product judgement,
not a lab benchmark, and not a guarantee against detection.

| Protocol | Client coverage | Anti-detection | Domain-free | Role here |
|---|---|---|---|---|
| **VLESS + REALITY + Vision** | **sing-box + mihomo** | High (REALITY camouflage) | ✅ | **Default primary path** |
| AnyTLS + REALITY | sing-box family only | Higher (padding + camouflage) | ✅ | `--protocol anytls-reality` |
| **Hysteria2** | sing-box + mihomo | Medium (salamander obfs) | Self-signed is enough — pinned for you | **Default second path** (UDP) |
| **VLESS + WebSocket + CDN** | sing-box + mihomo | Medium (the CDN sees the cleartext VLESS header) | Needs domain + cert | **Optional third path**; the only one that works when the bare IP is blocked |
| Trojan / classic TLS | Broad | Medium | ❌ needs a domain and a real site | Not shipped (heavier ops, no borrowed fingerprint) |
| Shadowsocks 2022 | Broad | Low (weak TLS-layer camouflage) | ✅ | Not shipped |
| VMess | Broad | Low (well-known characteristics) | ✅ | Not shipped |

> **Hysteria2 is not a REALITY replacement — it is a different lane.** It runs
> over UDP/QUIC: it often still passes when TCP is being interfered with, and
> some mobile paths drop whole UDP ranges. Both are shipped precisely because
> their failure causes are uncorrelated.

### Which path saves you, and when

| Path | Transport | When it is the only one that works | When it is dead |
|---|---|---|---|
| REALITY | tcp/443 + 2096/8880/40443 | Most Telecom / Unicom lines; fastest when direct works | Common on Mobile / BTV: SYN passes, ClientHello dropped |
| Hysteria2 | udp/443 + alternates | TCP under interference; lossy links | Some mobile paths block UDP wholesale |
| CDN relay | tcp/443 → CDN → origin | **The only way out when the server IP is blackholed** | Needs a domain; costs one hop |

Measurements (Xi'an Unicom AS4837, TUN bypassed, cross-polled), why direct
REALITY is not in the `⚡ Auto` group, how to choose edge IPs, and the full
measurement methodology: **[Networks in China](docs/en/CHINA-NETWORK.md)**.

### Keeping up with upstream

Protocol ecosystems, detection, and client support all change. Defaults here
track [sing-box](https://sing-box.sagernet.org/) / REALITY / mihomo upstream and
are recorded in the [Changelog](CHANGELOG.md). If mihomo ever gains
`reality-opts` for `anytls`, the default will be re-evaluated — but **the
criterion stays "can every target client kernel express it", not raw
performance.**

### Boundaries

- This project makes **no claim** about bypassing account risk controls, regional
  policy, or protocol detection.
- Multi-path improves the **probability that one path still works** when another
  fails. It is not absolute availability.
- All three paths still require your VPS to be alive. If the IP is fully blocked
  and no CDN domain is configured, this project cannot help you.

## Architecture

### Single-node (default)

```mermaid
flowchart LR
    Client["📱 Client<br/>sing-box · Karing · Hiddify<br/>Clash Verge · mihomo"]
    subgraph Paths["3 paths, raced by the client's url-test"]
      direction TB
      P1["🚀 REALITY<br/>tcp/443 + 2096/8880/40443"]
      P2["📡 Hysteria2<br/>udp/443 + alternates"]
      P3["☁️ VLESS+WS via CDN<br/>optional, needs a domain"]
    end
    Resi["🏠 Residential VPS<br/>sing-box"]
    Internet["🌍 Internet"]
    Client --> P1 --> Resi
    Client --> P2 --> Resi
    Client --> P3 -->|"nginx :8443 -> ws-ping-inject -> sing-box"| Resi
    Resi -->|"direct egress<br/>(residential IP visible to upstream)"| Internet
```

The three failure causes are uncorrelated: REALITY dies to ClientHello
interference on TCP, Hysteria2 to blanket UDP blocking, and the CDN relay only
to a missing domain — while being **the only path that survives a blackholed
IP**. Group ordering, probe parameters, and why direct REALITY is kept out of
the auto group: [Networks in China §4](docs/en/CHINA-NETWORK.md).

### Dual-node with smart routing

```mermaid
flowchart LR
    Client["📱 Client<br/>+ domain routing rules"]
    Resi["🏠 Residential VPS<br/>sing-box :443<br/>Leaf subscription :80"]
    DC["🏢 Data-center VPS<br/>sing-box :443<br/>Aggregator subscription :80"]
    OpenAI["OpenAI · Anthropic<br/>Netflix · Banking"]
    TG["Telegram · Discord"]
    Other["Other internet"]
    Client -->|"OpenAI/Anthropic/Netflix domains"| Resi
    Client -->|"Telegram/Discord domains"| DC
    Client -->|"default"| Resi
    Resi --> OpenAI
    Resi --> Other
    DC --> TG
    DC -.->|"polls /status"| Resi
```

The client downloads a *single* subscription URL from the aggregator. That URL returns a profile
listing **both** nodes plus the routing rules. The server picks the format from the client's
User-Agent — sing-box JSON for SFA/Karing/Hiddify, Clash YAML for mihomo/Stash — so one URL serves a
household running both. Traffic
accounting still reflects the residential node's quota: the aggregator polls the leaf and caches the
result, degrading gracefully if the leaf is briefly unreachable.


## Security

- All secrets are generated per-server and never committed.
- Repository CI gates on a hash-only denylist plus a secret-shape detector — no UUID, Reality key,
  or IP can land in a PR.
- The sing-box apt repository is verified against a pinned GPG fingerprint; installation refuses to
  proceed on mismatch.
- Threat model and reporting: [SECURITY.md](SECURITY.md).

> ⚠️ **The subscription URL is a credential.** The subscription server is plain HTTP on `:80` and
> the profile returned by `http://<ip>/<SUB_TOKEN>/` contains your node password — anyone on the
> path can read it, and anyone who learns the URL has your node. Do **not** paste the full URL into
> issues, screenshots, or chat groups, and do **not** put backup files into `FILE_DIR` (the same
> token path would serve them). For stronger protection, front it with a TLS reverse proxy, or fetch
> the profile once over `scp` and disable the subscription server. Full write-up in
> [SECURITY.md](SECURITY.md#subscription-url-exposure--订阅地址的暴露面).

## FAQ

The highest-frequency questions are below. The full set — 40+ answers covering installer flags,
subscription security, usage accounting, routing behaviour, dual-node, uninstall, and license
boundaries — lives in [docs/en/FAQ.md](docs/en/FAQ.md).

**Telegram file uploads stall on my residential VPS — "sending…" spins forever. What now?**
Telegram soft-throttles residential subnets that have historically hosted bots. Enable **dual-node
mode** and route `geosite:telegram` out through the data-center node; the problem goes away.

**OpenAI says "unsupported region" on my data-center VPS, but Telegram gets slow on the residential
one. How do I get both?**
That is the entire reason this project exists: OpenAI / Anthropic / banking / Netflix leave through
the residential exit, Telegram / Discord leave through the data-center node, and the client only
ever sees one subscription.

**What is the default protocol, and why not AnyReality?**
The default is **VLESS + REALITY + xtls-rprx-vision**, because it is the only anti-detection protocol
that **both sing-box and mihomo can express**. AnyReality's padding really is stronger, but mihomo's
`anytls` block has no `reality-opts` field — that node cannot be written into a Clash profile at all,
while **the server stays green and sing-box users notice nothing**. That trap cost this project a
month. If you want the padding and are certain every client is sing-box family, use
`--protocol anytls-reality`; the installer will tell you plainly that there is no Clash profile.
Full argument: [protocol choice](#protocol-choice-why-anyreality-is-no-longer-the-default).

**The bare IP is unreachable on my line (China Mobile / Broadcast-TV) and changing ports does not
help. Now what?**
Add the **CDN relay path**: `--cdn-domain relay.example.com --cdn-cert … --cdn-key …`, with the
domain proxied through a CDN such as Cloudflare. It is the only path that survives a blackholed IP.
Two things to know: the origin port cannot be 443 (sing-box owns it, and REALITY forwards non-proxy
traffic verbatim to its handshake target), so the installer accepts only the ports a CDN pulls from
over HTTPS; and the CDN closes a proxied WebSocket after ~100 s of no frames, which TCP keepalive
cannot prevent because it is hop-by-hop. This stack injects application-level WebSocket pings at the
origin — see [Networks in China §5](docs/en/CHINA-NETWORK.md).

**The client quits the instant I open it, or will not start after boot. Rebooting sometimes helps.**
Almost certainly a **remote rule-set deadlocking startup on the proxy**: sing-box downloads every
`type: remote` rule-set before it finishes starting and a failure is fatal — and the download goes
through a proxy group that, on a cold start, has no measurements and simply uses its first member,
which on your line is dead. Profiles from this project **inline every rule-set, so startup makes no
network request at all** and cannot fail this way. If it still happens, look for an **old
subscription from a decommissioned server** still sitting in the client; it brings the loop back.
Check with `grep -c raw.githubusercontent <client kernel.log>`.

**I just imported the subscription and now Chinese sites are slow. Is the node broken?**
No. In TUN mode there is no "global / direct" switch — routing rules alone decide what is proxied,
and incomplete rules push domestic traffic overseas. The profile this project generates ships four
rule layers (LAN-direct → ad-block → China-direct → proxy fallback) and works on import. If you
hand-edited the config or used a template from elsewhere, check it against
[routing rules](docs/en/ROUTING.md). Note that this project **inlines every rule-set into the
profile** — the download happens weekly on the server, never in the client at startup — plus a
~60-entry China-domain safety net that depends on no download at all.

**Is the subscription URL HTTPS? Can I share it?**
No — it is plain HTTP on `:80`, and the profile contains your node password. **Whoever has the URL
has your node.** Never share it publicly, paste it into an issue, or screenshot it. Add your own TLS
reverse proxy, or fetch the profile once with `scp` and shut the subscription server down. Also keep
backup files out of `FILE_DIR`, since the same token path would serve them. See
[SECURITY.md](SECURITY.md#subscription-url-exposure--订阅地址的暴露面).

**Does Reality need a domain and a certificate?**
Neither the REALITY nor the Hysteria2 path does — that is the biggest advantage over Trojan /
V2Ray-TLS. The default camouflage SNI is `addons.mozilla.org`, swappable for any high-reputation
domain. Hysteria2 uses a self-signed certificate generated by the installer and **pinned in the
profile** rather than a client-side `skip-cert-verify`, so it needs no domain and does not weaken
verification. **Only the optional CDN relay path needs your own domain and certificate.**

**Why does the default config block UDP 443 (QUIC / HTTP3)?**
REALITY and the CDN relay are TCP-only, so that QUIC traffic cannot traverse them. Left unblocked,
browsers retry HTTP/3 and only fall back to TCP after a timeout — which users experience as "pages
hang for a few seconds first". Blocking `udp:443` forces the fallback immediately. Note the rule
matches **client traffic**, not the tunnel: Hysteria2 itself runs over UDP and is unaffected. Pass
`--allow-quic` at install time to keep QUIC.

**How is this different from 3x-ui / x-ui / XHTTP-Installer?**
Those are built for "cheap VPS, bypass censorship" (multi-user, panel, hide the exit IP). This
project is built on the opposite premise — **your residential IP is an asset** — so it defaults to a
single UUID, does not hide the IP, and diverts only the few services hostile to residential subnets.

The rest — installer idempotency, why only Ubuntu 22.04+ / Debian 12+, pinning versions and
unattended installs, recovering a lost subscription URL, usage-accounting semantics, dual-node
deployment, uninstall and rollback, GPL-3.0 boundaries — is answered in the
[full FAQ](docs/en/FAQ.md).

## Documentation

| Guide | Link |
| --- | --- |
| Documentation index | [docs/README.md](docs/README.md) |
| **Networks in China (core)** | **[docs/en/CHINA-NETWORK.md](docs/en/CHINA-NETWORK.md)** |
| Beginner guide | [docs/en/BEGINNER_GUIDE.md](docs/en/BEGINNER_GUIDE.md) |
| FAQ | [docs/en/FAQ.md](docs/en/FAQ.md) |
| Usage examples | [docs/en/EXAMPLES.md](docs/en/EXAMPLES.md) |
| Deployment | [docs/en/DEPLOYMENT.md](docs/en/DEPLOYMENT.md) |
| Subscription server design | [docs/en/SUBSCRIPTION.md](docs/en/SUBSCRIPTION.md) |
| Dual-node + smart routing | [docs/en/DUAL-NODE.md](docs/en/DUAL-NODE.md) |
| Selective WARP egress & watchdog | [docs/en/WARP-EGRESS.md](docs/en/WARP-EGRESS.md) |
| Client routing rules | [docs/en/ROUTING.md](docs/en/ROUTING.md) |
| Client import | [docs/en/CLIENTS.md](docs/en/CLIENTS.md) |
| Troubleshooting | [docs/en/TROUBLESHOOTING.md](docs/en/TROUBLESHOOTING.md) |
| Comparison with similar tools | [docs/en/COMPARISON.md](docs/en/COMPARISON.md) |

For AI search engines and retrieval tools, see [llms.txt](llms.txt) — a compact machine-readable
summary of the project purpose, boundaries, docs map, and useful search phrases.

## Contributing

PRs welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first — lint gates are strict, and any change
touching install scripts must pass `make test && make lint && make redact && make examples`.

## License

GPL-3.0. See [LICENSE](LICENSE).

---

**Search keywords**: sing-box multi-path installer, VLESS Reality Hysteria2 CDN relay, sing-box
China network optimisation, AnyReality, AnyTLS Reality, residential IP proxy, VLESS Reality
residential proxy, sing-box residential installer, self-hosted proxy stack, Cloudflare WebSocket
idle timeout keepalive, sing-box remote rule-set FATAL startup, inline rule-set sing-box,
Cloudflare preferred IP end-to-end, alternate port iptables REDIRECT, OpenAI residential IP exit,
Telegram residential IP slow upload, Clash domain routing, dual-node smart routing,
alternative to 3x-ui for residential VPS, sing-box subscription server.
