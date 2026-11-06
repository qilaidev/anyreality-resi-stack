# Server-Side Selective Cloudflare WARP Egress (`--with-warp`)

> **TL;DR:** Your residential IP is the asset you paid for — **never route all traffic through WARP** (that turns an expensive residential ISP exit into a shared Cloudflare datacenter IP). `--with-warp` attaches a native sing-box WireGuard endpoint (`warp-ep`) on the server and enforces a **10-stage route table (C9 invariants)** so only AI/social platforms that challenge residential ASNs and the AAAA-only `challenges.cloudflare.com` Turnstile host exit through WARP, while Google, Netflix, Disney+, TikTok, banking, and everything else keep 100% native residential IP egress.

---

## 1. Why a residential-IP node still benefits from selective WARP

Even on a clean US/EU residential or ISP-leased static IP, operators run into two recurring failure modes:

1. **ASN / prefix reputation challenges on AI & social platforms**:
   `claude.ai`, `chatgpt.com`, `perplexity.ai`, `x.com`, `reddit.com`, and `medium.com` periodically trigger Cloudflare Turnstile loops or HTTP 403 blocks against entire ISP prefixes.
2. **AAAA-only Cloudflare Turnstile widget hosts on IPv4-only VPSes**:
   Sub-hosts under `challenges.cloudflare.com` (such as `brunhild.challenges.cloudflare.com`) publish **only IPv6 AAAA records** (no IPv4 A record). On an IPv4-only server that rejects IPv6 (`"ip_version": 6, "action": "reject"`), the CAPTCHA widget script cannot be fetched and verification pages spin forever.

### Why generic "global WARP" scripts ruin a residential VPS
Generic installers (`fscarmen/warp`, `233boy` global WARP outbound) replace the server's default outbound with WARP:
- **Result**: Netflix locks to Originals-only, Google triggers CAPTCHA storms, PayPal/Stripe/banking flag the shared VPN exit, and TikTok detects a datacenter ASN.

---

## 2. The 10-Stage Selective Route Architecture (C9 Invariants)

Enabling `--with-warp` (or running `/usr/local/sbin/anyreality-resi-stack-warp enable`) writes `02_warp_endpoints.json` and updates `03_route.json` and `05_dns.json` under `/etc/sing-box/conf/`.

`03_route.json` enforces this exact **10-stage rule order** (verified by `warp_egress.py audit` and `healthcheck.sh`):

| Stage | Match condition | Action / Outbound | Why this exact position matters |
|---:|---|---|---|
| 1 | `action: sniff` | Sniff TLS SNI / HTTP Host | Must run first so domain rules match connections dialled by IP |
| 2 | `ip_is_private: true` | `direct` | Protect RFC1918 and loopback traffic |
| 3 | `domain_suffix: [challenges.cloudflare.com]` | `warp-ep` | **Must precede stage 4 (`ip_version: 6` reject)!** Because Turnstile widget hosts are AAAA-only, routing them into `warp-ep`'s dual-stack `/32 + /128` tunnel lets IPv4-only VPSes solve Turnstile challenges natively |
| 4 | `ip_version: 6` | `action: reject` | Fast-reject all other IPv6 targets on IPv4-only hosts |
| 5 | `inbound: [warp-probe-in]` | `warp-ep` (permanently pinned) | Dedicated to `127.0.0.1:10809`. **Stays pinned to `warp-ep` even when the watchdog degrades to `direct`**, so the watchdog can detect when the tunnel recovers |
| 6 | `domain_suffix: EXCLUDE_DIRECT` | `direct` | **Must precede `WARP_SUFFIX` and `CF_CIDRS`!** Keeps Google, YouTube, Apple, Microsoft, GitHub, Netflix, Disney+, TikTok, PayPal, Stripe, and Speedtest on the native residential IP even when sub-assets use Cloudflare CDN |
| 7 | `domain_suffix: WARP_SUFFIX` + `domain: WARP_EXACT` | `warp-ep` | Routes `claude.ai`, `anthropic.com`, `chatgpt.com`, `openai.com`, `perplexity.ai`, `x.com`, `reddit.com`, `medium.com`, etc. through WARP |
| 8 | `inbound: [hy2-in, vless-ws-in]` | `direct` | High-throughput UDP/CDN paths skip post-resolve CIDR inspection for non-WARP domains |
| 9 | `action: resolve, strategy: ipv4_only` | Resolve domain to IPv4 | **Must precede stage 10 (`ip_cidr`)!** Without `action: resolve`, domain traffic never matches an `ip_cidr` rule in sing-box |
| 10 | `ip_cidr: CF_CIDRS` | `warp-ep` | Catches remaining Cloudflare-fronted sites across Cloudflare's 15 official IPv4 CIDRs |

All other traffic falls through to `final: direct` (your native residential IP).

---

## 3. Auto-Degrade & Self-Healing Watchdog (`warp-watchdog.timer`)

If a Cloudflare WARP endpoint experiences an outage and `warp-ep` stops passing traffic, static routing would blackhole Claude/ChatGPT.

`warp-watchdog.timer` runs `warp_egress.py watchdog` every 2 minutes:

```text
[Normal state: outbound = "warp-ep"]
   │
   ├─ Probes https://cp.cloudflare.com/generate_204 via 127.0.0.1:10809 (warp-probe-in)
   │
   ├─ 3 consecutive failures (~6 minutes)
   ▼
[Degraded state: rewrites WARP rules in 03_route.json to "direct" & reloads sing-box]
   │  (Stage #5 `warp-probe-in -> warp-ep` stays pinned to keep probing the tunnel)
   │
   ├─ 3 consecutive probe successes
   ▼
[Recovered state: restores "warp-ep" in 03_route.json & reloads sing-box]
```

---

## 4. Operations & CLI Reference

### Enable at install time
```bash
bash install/install.sh \
  --node-name "US-Resi-01" \
  --sni addons.mozilla.org \
  --with-subscription \
  --with-warp
```

Pass `--warp-config /path/to/warp-credentials.json` if you want to supply pre-registered credentials instead of auto-registering.

### Manage on an existing node
The installer places `/usr/local/sbin/anyreality-resi-stack-warp` on the server:

```bash
# 1. Register a new free WARP keypair (saved to /etc/anyreality-resi-stack/warp-credentials.json, mode 0600)
anyreality-resi-stack-warp register

# 2. Enable selective WARP egress
anyreality-resi-stack-warp enable --credentials /etc/anyreality-resi-stack/warp-credentials.json

# 3. Audit 03_route.json against all C9 ordering invariants (add --live-cf-ips to compare against cloudflare.com/ips-v4)
anyreality-resi-stack-warp audit --live-cf-ips

# 4. Run one watchdog probe cycle manually and inspect state JSON
anyreality-resi-stack-warp watchdog

# 5. Verify split egress via the two loopback verification ports
curl -x http://127.0.0.1:10809 https://cloudflare.com/cdn-cgi/trace   # forced warp-ep -> warp=on
curl -x http://127.0.0.1:10810 https://cloudflare.com/cdn-cgi/trace   # main route table -> warp=on
curl -x http://127.0.0.1:10810 https://ipinfo.io/ip                   # hits EXCLUDE_DIRECT -> native residential IP

# 6. Disable WARP egress and restore baseline direct routing
anyreality-resi-stack-warp disable
```
