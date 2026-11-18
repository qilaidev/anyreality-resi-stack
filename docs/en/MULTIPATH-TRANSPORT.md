# Multi-Path Transport Resilience, Lossy-Link Tuning, and End-to-End Measurement

> [!IMPORTANT]
> **Compliance & Acceptable Use Prerequisite**: This document covers wide-area network (WAN) transport engineering across high-RTT, lossy, and CGNAT links for authorized self-hosted edge infrastructure and protocol research only. Read [Legal Compliance & Disclaimer](../../DISCLAIMER.md) before deployment.

> This document answers a core systems engineering question: **why an edge gateway that reports 100% green on the server behaves completely differently across distinct carrier ASNs, CGNATs, and time windows — and how to engineer uncorrelated multi-path transport failover with deterministic verification.**
>
> Every architectural rule here maps to a real failure mode or controlled end-to-end measurement. Hypotheses that sounded plausible on paper but failed in production measurements are documented alongside their disproof so maintainers never re-introduce them.

---

## 0. Executive Summary

**Across heterogeneous WAN paths, any single transport protocol will eventually degrade or stall under specific carrier QoS policies, CGNAT timeouts, or asymmetric routing — while the server logs nothing wrong.** This stack therefore exposes three complementary transport paths by default and lets the client race them via `urltest`:

| Path | Transport | Where It Excels | Typical Constraint |
|---|---|---|---|
| **REALITY** | TCP 443 + alternates | Clean fixed-broadband routes; zero relay hop overhead | Susceptible to middlebox TLS ClientHello stalling or port-based QoS on strict CGNAT/mobile networks |
| **Hysteria2** | UDP / QUIC | High-loss, high-BDP trans-oceanic links where TCP congestion control collapses | Certain enterprise or mobile carrier networks drop sustained UDP/443 flows |
| **CDN Relay** | TCP 443 → Anycast CDN → origin | **Survives direct-origin BGP route blackholes, severe peering loss, or strict egress firewalls** | Requires a user-owned domain and certificate; adds one relay hop |

These three paths are **orthogonal, not redundant** — their failure modes do not overlap.

---

## 1. Protocol Selection: Why AnyReality Is Not the Default

Earlier iterations defaulted to **AnyTLS + REALITY**. Viewed purely from the server side, the engineering case was strong: configurable frame padding smooths nested-TLS packet signatures, REALITY eliminates certificate provisioning overhead, and weak-link throughput outperformed classic TLS tunnels. **Making it the default was still a mistake.**

The flaw was evaluating only the server while ignoring **client kernel ecosystem coverage**:

> mihomo's `anytls` proxy configuration block **has no `reality-opts` field**, leaving nowhere to express `public-key` or `short-id` ([mihomo docs](https://wiki.metacubex.one/en/config/proxies/anytls/) · [issue #2155](https://github.com/MetaCubeX/mihomo/issues/2155)). Consequently, in Clash-family subscriptions **the primary node cannot be serialized at all.**

The failure mode is completely silent from the server:

- Server health checks are green and `sing-box check` passes;
- Clients running the `sing-box` kernel work flawlessly;
- **Clash / mihomo users silently receive a profile missing its primary node, seeing fewer entries rather than an explicit error.**

> **Selection Rule:** Ask *"can every target client kernel express this node?"* before asking *"which protocol benchmarks fastest?"*. A default supported by only half the client ecosystem silently breaks the other half.

Current policy:

- **Default `--protocol vless-reality`** (`VLESS + REALITY + xtls-rprx-vision`) — natively supported across both `sing-box` and `mihomo` ecosystems;
- **Opt-in `--protocol anytls-reality`** — retained for deployments standardized exclusively on `sing-box` clients that want stronger padding; `build_profile.py` explicitly refuses to emit an incomplete Clash YAML when selected.

### Corollary: Audit Dormant Scripts and Docs After Retiring Defaults

**Documentation that confidently points to a retired architecture is worse than no documentation.** Whenever protocol defaults or config schemas change, audit every helper script and doc page to eliminate drift.

---

## 2. Port Strategy: Primary 443 Plus Kernel-Redirected Alternate Ports

An initial baseline benchmark on a fixed-broadband WAN path produced an apparently clear-cut result:

| Test Case | Measured Result |
|---|---|
| Bare TCP 3-way handshake (22 / 80 / 443 / 2087) | ✅ All succeeded |
| TLS session over high TCP ports (2053 / 2083 / 2087) | ❌ 440 consecutive timeouts |
| TLS session over standard **443** | ✅ Stable (195–242 ms) |

On that path, middleboxes passed TCP `SYN` packets on high ports but dropped subsequent TLS handshake payloads. Had we stopped there, we would have hard-coded port 443 alone.

**Five weeks later on the exact same physical circuit, the ranking inverted:**

| Port | End-to-End Handshake & Initial Response |
|---|---|
| 443 | 1520–3783 ms (congested carrier QoS queue) |
| 8880 | **1269 ms** |
| 40443 | **1264 ms** |

Port 443 had become the most heavily throttled queue on that route, while a separate mobile CGNAT path stalled for 12 seconds after `ClientHello` on 443.

> **Key Lesson:** Point-in-time port benchmarks on a single carrier path expire. WAN traffic shaping and middlebox policies shift across carriers, ports, and weeks.

Current architecture: **listen on `443` as primary (highest firewall/Wi-Fi compatibility) and expose `2096 / 8880 / 40443` as alternate ports raced automatically by client `urltest`.**

Alternate ports are implemented as **`iptables` / `ip6tables` `nat/PREROUTING` `REDIRECT` rules** rather than extra user-space listeners:

- Zero duplication in `sing-box` inbound configs;
- Clean teardown by flushing the dedicated `ANYREALITY_ALTPORT` chain without touching container or host NAT rules;
- Because destination port translation happens in `nat/PREROUTING`, `filter/INPUT` sees port `443` — **UFW requires no extra rules for alternate ports**;
- **Operational note:** Alternate ports **do not appear in `ss -tlnp`**. Verify them via kernel NAT counters instead:

```bash
iptables -t nat -S ANYREALITY_ALTPORT
```

---

## 3. Cold-Start Deadlocks: Eliminating Boot-Time Remote Rule-Set Fetches

This is the single highest-impact client failure mode: **the client app exits immediately on launch or enters a boot-restart loop.**

### How the Deadlock Forms

1. `sing-box` fetches every `type: remote` rule-set **synchronously during startup**, exiting with `FATAL: initialize rule-set` if any fetch fails;
2. When `download_detour` points to an `urltest` group, **cold start has zero latency samples and blindly uses member #0**;
3. On a clean link where member #0 responds, startup finishes in ~1 second;
4. On a degraded or filtered link where member #0 times out after 5 seconds, the kernel exits `FATAL` → the GUI supervisor restarts it → it hits member #0 again indefinitely.

### Three Mandatory Defenses

| Layer | Implementation |
|---|---|
| **100% Inline Rule-Sets** | Every `rule_set` is compiled into the subscription as `type: inline` — **zero network requests during client startup**. `check_profile.py` rejects any `type: remote` entry before publication |
| **Cold-Start Group Ordering** | `⚡ Auto` places the broadest-reach transport (the CDN relay when enabled) in slot 0 so initial traffic uses the highest-survival path |
| **Server-Side Weekly Refresh** | Rule-set downloads run weekly on the server (`refresh-rulesets.timer`) over a clean datacenter/VPS uplink, retaining the previous valid snapshot if an upstream fetch fails |

Measured on a production host, **inlining adds minimal wire overhead when decompiled from compact upstream `.srs` binaries**:

| Rule-Set | Entries | Raw JSON Size |
|---|---:|---:|
| `geosite-cn` | 9,131 | 152 KiB |
| `geoip-cn` | 7,876 | 142 KiB |
| `geosite-category-ads-all` | 890 | 18 KiB |
| `geosite-cn-extra` (repo supplement) | 71 | 1 KiB |

The complete generated profile is **0.56 MiB** raw and **~81–84 KiB on the wire** with `Accept-Encoding: gzip` — replacing five separate boot-time requests (~280 KB total) with a single compressed sync and **zero startup network dependency**.

> ⚠️ **Source Bloat Trap:** Flattened third-party JSON mirrors expand the same regional set to **111,305 entries / 1.7 MiB** (~3.36 MiB profile). `fetch-rulesets.sh` therefore decompiles official SagerNet `.srs` binaries locally first and uses JSON mirrors strictly as an emergency fallback.

```bash
# Client self-check: non-zero count indicates a legacy profile still fetching remote rule-sets
grep -c "raw.githubusercontent" <client kernel.log>
```

---

## 4. Group Ordering: Why `⚡ Auto` Excludes Direct REALITY When Multi-Path Is Active

Because `urltest` uses slot 0 before its first probe completes, default ordering when multiple paths are active is **`☁️ CF Relay` → `📡 Hysteria2`**, keeping `🚀 REALITY` one click away inside `🎯 Select`. Two engineering reasons drive this:

1. **Preventing stalled probes from jamming group health checks:** On networks where middleboxes stall TCP handshakes for 7–12 seconds, probing direct TCP every cycle keeps worker routines tied up in timeouts.
2. **Multiplexed session reuse on high-RTT links:** Across controlled cross-polled benchmarks on a 220 ms trans-Pacific broadband circuit (local TUN bypassed, non-CDN target origin):

| Transport Path | Median TTFB (6 cross-polled rounds) | Median Throughput (2 MB payload, 3 rounds) |
|---|---|---|
| Direct Hysteria2 (UDP 443/2096/8880) | **0.62–0.82 s** | 664–690 KB/s |
| Anycast CDN Relay (8 edges) | 0.86–1.32 s | 466–856 KB/s |
| Direct VLESS+REALITY (4 TCP ports) | **1.69–2.95 s** | **236–342 KB/s** |

`xtls-rprx-vision` cannot be combined with `multiplex`, so every new stream pays a full TCP + TLS handshake (~0.66 s at 220 ms RTT), whereas CDN WebSocket uses `h2mux` stream multiplexing and Hysteria2 reuses QUIC sessions. Where direct TCP is fastest on your circuit, select `🚀 REALITY` manually; when it is the sole enabled path, `build_profile.py` places it in `⚡ Auto` automatically.

### Group Tuning Invariants

| Parameter | Value | Engineering Rationale |
|---|---|---|
| `interrupt_exist_connections` | **`false`** | `true` tears down active streams on every probe cycle and breaks `h2mux` sessions |
| `interval` | **`5m`** | Avoids continuous timeout churn on paths with slow-failing members |
| `tolerance` | **`80 ms`** | Prevents group flapping when long-haul WAN jitter exceeds minor latency differences |
| `connect_timeout` | **Unset** | High-RTT WAN handshakes legitimately take 1.3–6.5 s; aggressive 4–8 s caps kill valid sessions |
| Clash Group Type | **`url-test` (never `fallback`)** | `fallback` pins traffic to the first merely-reachable node even when it is 10× slower |

---

## 5. CDN WebSocket Relay: Solving the Exact ~2m05s Idle Disconnect

After enabling a CDN-proxied WebSocket relay, operators commonly observe connections dropping at **almost exactly 2m05s–2m07s**.

Neither `nginx` `proxy_read_timeout` (set to `3600s`) nor client TCP keepalives (terminated hop-by-hop at the CDN edge) cause this. **The root cause is the CDN edge's ~100-second idle timeout on proxied WebSockets when zero WebSocket frames traverse the connection**, combined with `sing-box` mux protocols (`h2mux`/`smux`/`yamux`) emitting no WebSocket-layer `PING` frames.

This stack solves it on the origin data path via `scripts/ws_ping_inject.py`:

```text
Anycast CDN --TLS--> nginx:8443 --WS--> ws-ping-inject:18444 --TCP--> sing-box:18443
```

After the HTTP `101` upgrade, `ws_ping_inject.py` tracks WebSocket frame headers on the server-to-client stream and injects an empty `PING` control frame (opcode `0x9`) every 25 seconds **strictly on frame boundaries** (preventing mid-frame stream corruption), with zero-buffer passthrough for oversized frames (>16 MiB) and `TCP_NODELAY` on loopback sockets.

### Additional CDN Relay Invariants

- **Mux protocol must be `h2mux` (`max_connections: 4`)**: `yamux`/`smux` over CDN WebSocket triggers `context canceled` or 5-minute drops.
- **Origin port cannot be `443`**: `sing-box` owns `443`; the installer restricts `--cdn-origin-port` to HTTPS-capable CDN origin ports (`2053 / 2083 / 2087 / 2096 / 8443`).
- **Origin stealth & CIDR allowlisting**: UFW restricts the origin port to official Cloudflare IPv4/IPv6 origin-pull CIDRs, and `nginx` sets `ssl_reject_handshake on` on unknown SNIs so IP scanners never learn `CDN_DOMAIN`.

---

## 6. Anycast Edge IP Selection: Never Rank by TCP Handshake RTT

Ranking CDN edge IPs by TCP handshake RTT failed twice across distinct carrier types:

| Network Type | Fastest Edge Handshake | Actual End-to-End Throughput |
|---|---|---|
| Mobile CGNAT carrier | `104.19.63.243` (**61 ms** handshake) | **0.16 Mbps** end-to-end |
| Fixed broadband carrier | `104.20.29.23` (**89.5 ms** handshake) | **108 KB/s (last place)** — 3× slower than 220 ms edges |

**A TCP handshake measures only `client → CDN edge`, completely ignoring the `CDN edge → origin` backhaul leg.**

`scripts/pick-cf-ip.py` uses TCP handshakes strictly to screen out unreachable ranges, then ranks survivors via **cross-polled end-to-end HTTPS TTFB** through your actual origin, prioritizing **100% success rate and `/16` prefix diversity** and warning explicitly when within-edge jitter exceeds between-edge differences.

```bash
# Run from the client network being tuned, binding to the physical NIC to bypass local TUN
python3 scripts/pick-cf-ip.py --domain example.com --interface en0
```

---

## 7. Five Rules for Reliable Network Measurement

1. **Bypass your own local TUN and proxy env vars first:** Verify physical ISP egress before benchmarking (`curl --noproxy '*' --interface en0 https://checkip.amazonaws.com`). `pick-cf-ip.py --interface` uses `IP_BOUND_IF` (macOS) / `SO_BINDTODEVICE` (Linux) to bind routing at the socket level.
2. **Interpret empty logs against `log.level`:** Under `warn` level, healthy connections emit zero log lines. Measure actual traffic via kernel counters (`iptables -t nat -L ANYREALITY_ALTPORT -v -n`), not log volume.
3. **Separate signal from WAN jitter via cross-polling:** Interleave candidates (`A → B → C → D`) across rounds and act only when between-group median differences exceed within-group spread.
4. **Measure end-to-end, never single-hop:** Never extrapolate full-tunnel throughput from first-hop ping or TCP SYN RTT.
5. **Verify live runtime state, not files on disk:** Check `nginx -T` (not just `nginx -t`), `sysctl -n` (not `/etc/sysctl.d/` text), and `check_profile.py` (not JSON syntax alone).

---

## 8. Kernel Sysctl Tuning: Single File & Live Verification

Because `/etc/sysctl.d/*.conf` files load in lexical order and silently override earlier keys, the installer consolidates all tuning into `/etc/sysctl.d/99-anyreality.conf`, removes legacy split files, and verifies live kernel values via `sysctl -n` and `scripts/check_sysctl.py`:

| Parameter | Value | WAN Engineering Rationale |
|---|---|---|
| `tcp_congestion_control` / `default_qdisc` | `bbr` / `fq` | Throughput and queue-delay baseline for lossy long-haul WAN paths |
| `tcp_slow_start_after_idle` | `0` | Prevents cwnd reset between bursts on ~200 ms RTT persistent tunnels |
| `rmem_max` / `wmem_max` | `33554432` (32 MiB) | Matches ~25 MB BDP (200 ms × 1 Gbps) so socket buffers never cap throughput |
| `tcp_keepalive_time` / `_intvl` / `_probes` | `60` / `15` / `4` | Keeps mappings alive across 30–90 s carrier CGNAT idle reclamation windows |
| `tcp_retries2` | `8` | Fails dead TCP sockets faster on lossy links instead of hanging ~15 minutes |
| `tcp_notsent_lowat` | `131072` (128 KiB) | Prevents bulk writes from queueing ahead of interactive frames in kernel buffers |
| `netdev_max_backlog` | `16384` | Absorbs high-rate UDP/QUIC (`Hysteria2`) packet bursts without NIC ring drops |

---

## 9. Regional Split-Tunneling & DNS Ordering Invariants

In virtual NIC (`TUN`) mode, routing rules govern every packet on the host. Slow local website loads almost always trace back to local traffic hairpinning across a remote trans-oceanic gateway rather than server bandwidth limits.

`scripts/build_profile.py` and `scripts/check_profile.py` enforce two critical ordering invariants:

1. **`action: resolve` must precede IP/CIDR rules (and be omitted when unused):** `sing-box` does not resolve domain names implicitly to evaluate `geoip` or `ip_cidr` rules; without an explicit preceding `resolve`, IP rules remain syntactically valid yet permanently inert for domain traffic.
2. **DNS-layer `prefer_ipv4` exemption for AAAA-only challenge hosts:** Subdomains under `challenges.cloudflare.com` publish IPv6 `AAAA` records exclusively. Under global `ipv4_only` DNS, the exemption must live in `dns.rules` (`prefer_ipv4` routed via `dns-remote`) so TUN applications receive a valid resolution instead of an empty DNS answer before routing ever runs.

---

## 10. Six Production Maintenance Rules

1. **Allowlist UDP explicitly alongside TCP:** `ufw allow 443` opens TCP only; Hysteria2 requires `443/udp`.
2. **Treat deployed connection credentials as immutable unless compromised:** Avoid arbitrary periodic credential rotation that disconnects existing clients without cause.
3. **Update server inbounds and client profiles atomically** via `rebuild-profiles.sh`.
4. **Gate publication on build → structural check → `sing-box check` → atomic rename.**
5. **Keep every data-path daemon (`ws-ping-inject`, `nginx`, NAT chains) in `healthcheck.sh`.**
6. **Use symlinks rather than static file copies for fallback targets** to prevent silent configuration drift.

---

## Appendix: Full Read-Only Host Health Check

```bash
anyreality-resi-stack-healthcheck

python3 /usr/local/lib/anyreality-resi-stack/check_profile.py \
  /etc/anyreality-resi-stack/files/profile.json \
  /etc/anyreality-resi-stack/files/profile.yaml
python3 /usr/local/lib/anyreality-resi-stack/check_sysctl.py
```

See also: [Legal Compliance & Disclaimer](../../DISCLAIMER.md) · [Deployment](DEPLOYMENT.md) · [Client Import](CLIENTS.md) · [Routing Rules](ROUTING.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Operations](OPERATIONS.md)
