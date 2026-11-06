# Networks in China: three paths, why those three, and how to measure

> This document answers one question: **why a node that "connects fine" behaves
> completely differently across carriers and across weeks — and how to make it
> reliably usable anyway.**
>
> Every decision here corresponds to a real outage or a real measurement round.
> Where something sounded reasonable and was then disproved, the disproof is
> kept — because the reasonable-sounding version is exactly what the next person
> will reach for.

---

## 0. The short version

**A single path will eventually fail on some line, and when it does the server
shows nothing wrong.** So this project exposes three paths by default and lets
the client race them:

| Path | Transport | When it is the only one that works | When it is dead |
|---|---|---|---|
| **REALITY** | TCP 443 + alternates | Most China Telecom / Unicom lines; fastest when direct works | Common on China Mobile / Broadcast-TV: SYN passes, ClientHello is dropped |
| **Hysteria2** | UDP | When TCP is being actively interfered with | Some mobile paths drop whole UDP ranges |
| **CDN relay** | TCP 443 → CDN → origin | **The only way out when the bare server IP is blackholed** | Needs a domain; costs one extra hop |

These are not redundant. They are complementary — their failure causes are
uncorrelated.

---

## 1. Protocol: why AnyReality is no longer the default

This repository used to default to **AnyTLS + REALITY**, and the argument was
sound: custom padding suppresses TLS-in-TLS characteristics, REALITY supplies
server-side camouflage, and it measured better than Trojan on weak links.
**The conclusion was still wrong.**

The mistake was not in the reasoning. It was that protocol selection looked only
at the server and never at **client kernel coverage**:

> mihomo's `anytls` block has **no `reality-opts` field**. There is nowhere to
> put `public-key` / `short-id`
> ([docs](https://wiki.metacubex.one/en/config/proxies/anytls/) ·
> [issue #2155](https://github.com/MetaCubeX/mihomo/issues/2155)).
> So in a Clash-family subscription **the primary node cannot be written down at
> all.**

The shape of this failure is worth memorising:

- The server is entirely green, `sing-box check` passes.
- Users on sing-box kernels are completely fine and have nothing to report.
- **Only Clash users have no primary node — and what they see is "a few nodes
  missing from the list", not an error.**

Nothing on the server side indicates anything is wrong, which is why it took a
month to find.

> **Rule:** ask "can every client kernel I need to support express this node?"
> *before* asking "is it fast?". A protocol only one kernel supports silently
> removes half your users.

Hence today:

- **Default `--protocol vless-reality`** (VLESS + REALITY + xtls-rprx-vision) —
  both sing-box and mihomo can complete the handshake.
- `--protocol anytls-reality` is still supported and its padding really is
  better. **But choosing it means there is no Clash profile at all.** The
  installer says so, and `build_profile.py` refuses to emit YAML rather than
  emitting a crippled one.

### Corollary: after retiring a protocol, go grep the scripts and the docs

**A document that confidently points the wrong way is worse than no document.**
After any protocol or architecture change, search for every script that would
still deploy the old shape — especially the ones not wired into cron or systemd,
which look harmless — and for every doc still recommending the old route.

---

## 2. Ports: 443 is the default, and the alternates are not optional

A July 2026 measurement on a Unicom line was very clean:

| Test | Result |
|---|---|
| Bare TCP handshake (22 / 80 / 443 / 2087) | ✅ all fine |
| REALITY over TCP 2053 / 2083 / 2087 | ❌ timeout — 440 connections, zero successes |
| REALITY over TCP **443** | ✅ usable (195–242 ms) |

The interference shape was **SYN allowed, TLS ClientHello dropped**. The
conclusion looked solid: high ports are useless, only 443 works.

**Five weeks later, same line, the conclusion inverted:**

| Port | Latency |
|---|---|
| 443 | 1520–3783 ms |
| 8880 | **1269 ms** |
| 40443 | **1264 ms** |

443 had become the slowest one. In the same period Broadcast-TV blackholed the
whole IP and China Mobile hung for 12 s after the ClientHello on 443.

> **The lesson is not "use high ports". It is that a single measurement on a
> single line expires.** Interference is intermittent, differs per carrier, and
> changes week to week. Every "we tested it, port X does not work" has a shelf
> life.

So: **443 as the primary port** (best compatibility, least suspicious), with
**2096 / 8880 / 40443 as alternates**, and the client's url-test picking
whichever is alive.

The alternates are **iptables NAT REDIRECTs**, not extra listeners:

- sing-box config does not change at all — no second config to keep in sync.
- Rollback is flushing one chain we own; Docker's NAT rules are never touched.
- Because the rewrite happens in `nat/PREROUTING`, `filter/INPUT` only ever sees
  443, so **UFW needs no rule for the alternates**.
- **Cost: these ports never appear in `ss -tlnp`. That is expected, not a
  fault — do not "fix" it.**

```bash
# Check they are actually in effect (counting kernel rules, not files)
iptables -t nat -S ANYREALITY_ALTPORT
```

---

## 3. The client that will not start: a loop that needs the proxy to reach the proxy

This is the highest-impact trap in the project, because **the client does not
come up at all** — and the user's description is "the app quits the moment I
open it".

### The chain

1. sing-box downloads every `type: remote` rule-set **during startup**, and any
   failure is `FATAL`.
2. The download goes through the group named by `download_detour` — and **on a
   cold start urltest has no measurements yet, so it simply uses the first
   member.**
3. On Unicom the first member works → done in a second, everything is fine.
4. On Mobile the first member is dead → 5 s timeout → `FATAL: initialize
   rule-set` → the kernel refuses to start → the supervising app sees the kernel
   exit → restarts it → into the same wall.

"Rebooting the computer fixes it" only means the timing changed and that
download happened to succeed. **It was never actually fixed.**

The same rule-set files on a jittery line went from 0.6 s to "8 KB times out
after 10 s" within minutes. A first import is very likely to hit this, and the
user has no way to see why.

### Three defences, all required

| Layer | What this project does |
|---|---|
| **Subscription** | Every rule-set is `inline` — zero network at startup. `check_profile.py` rejects any `type: remote`, and `rebuild-profiles.sh` publishes nothing that fails validation |
| **Group order** | `⚡ Auto` puts the path that works on **both** kinds of line (the CDN relay) first, so that one cold-start request goes somewhere alive |
| **Client-local** | Compile the `.srs` files your client is missing (below) |

Inlining costs less than people expect — **provided the rule-sets come from the
right source.** Measured on a real host:

| Rule-set | Entries | Size |
|---|---:|---:|
| `geosite-cn` | 9,131 | 152 KiB |
| `geoip-cn` | 7,876 | 142 KiB |
| `geosite-category-ads-all` | 890 | 18 KiB |
| `geosite-cn-extra` (maintained here) | 71 | 1 KiB |

The resulting profile is **0.56 MiB**, **81 KiB gzipped**, and the subscription
server compresses per `Accept-Encoding`, so about **84 KB** actually crosses the
wire. The previous arrangement was 280 KB across five requests; this is one
84 KB request — and **zero requests during startup.**

> ☠️ **The wrong source turns that into 3.4 MB.** Another commonly used mirror
> flattens every attribute variant of the CN set: same coverage, **111,305
> entries / 1.7 MiB**, and a 3.36 MiB profile. These rules are *inlined*, and
> the profile is what a phone re-downloads on a bad line — so that difference is
> the entire subscription. `fetch-rulesets.sh` therefore decompiles SagerNet's
> `.srs` locally first and only falls back to the mirror, printing a note when
> it does.

The download moved to the server, on a weekly `refresh-rulesets.timer`: the
server has a clean uplink, a failure keeps last week's copy, and a client boot
never touches the network.

```bash
# Self-check: if this appears in the client log, the loop is still there
grep -c "raw.githubusercontent" <your client kernel.log>
```

> ⚠️ **An old subscription re-introduces the loop.** If a profile from a
> decommissioned server is still in the client, its `type: remote` +
> `download_detour` brings the deadlock back — **even when it is not the
> selected profile.** Delete old subscriptions properly.

---

## 4. Groups: why `⚡ Auto` contains no direct REALITY

urltest has no measurements on the first connection and **can only use its first
member**. Slot 0 therefore decides whether the client works in the seconds after
launch — and on a line where the bare IP is blackholed, only the CDN path
answers.

Default order: **CDN → Hysteria2**, with direct REALITY reachable only by hand.
Two reasons:

**① Probing it jams the group.** On a line that hangs the ClientHello for 7–12 s,
every probe cycle has a member slowly failing.

**② It came last in two independent measurement rounds.** Xi'an Unicom AS4837,
TUN bypassed, cross-polled, deliberately targeting non-CDN origins:

| Path | Median TTFB (6 rounds) | Median throughput (2 MB, 3 rounds) |
|---|---|---|
| Direct Hy2 (443/2096/8880) | **0.62–0.82 s** | 664–690 KB/s |
| CDN relay (8 edges) | 0.86–1.32 s | 466–856 KB/s |
| Direct VLESS+REALITY (4 ports) | **1.69–2.95 s** | **236–342 KB/s** |

Four independent ports last on both metrics is not noise (the between-group
difference of ~400 KB/s clearly exceeds any single node's own 125–205 KB/s
spread). Because **all four ports are slow together**, this is not per-port
interference — the bare-IP TCP path itself is being suppressed.

The structural explanation points the same way: REALITY uses
`xtls-rprx-vision`, and **vision and multiplex are mutually exclusive**, so every
new connection pays a full TCP+TLS handshake (220 ms RTT × 3 ≈ 0.66 s on that
line). The CDN path has h2mux reuse and Hysteria2 has QUIC session reuse;
neither pays it.

> ⚠️ **This does not contradict "Unicom can reach the bare IP".** Bare 443 was
> still reachable (220 ms handshake, 6/6 success). It was just **slow**.
> "Reachable" and "fast" are two different things — do not infer one from the
> other.
>
> If direct is the fast path on your line (many Telecom lines), select
> `🚀 REALITY` by hand, or edit `auto_members()` in `scripts/build_profile.py`.

When only one path exists (no CDN configured, Hysteria2 disabled), it goes into
`⚡ Auto` as you would expect — the rule above exists to avoid *probing* a path
that stalls, not because that path is unusable.

### The other group parameters, each from an incident

| Setting | Value | Why |
|---|---|---|
| `interrupt_exist_connections` | **false** | true makes every probe cycle tear down the tunnel currently carrying traffic; on the CDN path it also re-splits the mux and stalls for minutes |
| `interval` | **5m** | At 30 s a member that takes 7–12 s to fail keeps the channel permanently busy failing |
| `tolerance` | **80 ms** | Without hysteresis the group flaps between two edges whose difference is pure noise (cross-border sd reaches 1.05 s) |
| `connect_timeout` | **unset** | Measured handshakes run 1.3–6.5 s and CDN TTFB is often 1–4 s. A 4–8 s cap kills connections that would have succeeded |
| Clash group type | **url-test, never fallback** | fallback takes the first member that is merely *alive*, i.e. pins you to the slowest path (11.12 s vs 1.20 s measured on one client) |

---

## 5. The CDN relay: it connects, then dies every 2m05s

The most common report after enabling the CDN path is "it connects, then drops
after a while" — and the drop is **suspiciously exact**: 2m05s / 2m06s / 2m07s,
over and over.

The three obvious suspects are **all wrong**:

| Suspect | Reality |
|---|---|
| nginx `proxy_read_timeout` | Already 3600 s — it cannot produce 125 s |
| Client TCP keepalive / `keep-alive-idle` | TCP keepalive is **hop-by-hop**; it terminates at the CDN edge and the CDN never sees it |
| "The auto group picked a bad node" | Every node behaves the same, because the cause is not the node |

The actual cause is the **CDN's idle timeout for a proxied WebSocket** (~100 s on
ordinary plans): with no frames in either direction it closes the connection.
Keeping it alive requires an **application-level ping** — something that becomes
an actual WebSocket frame. sing-box's h2mux / smux / yamux emit none.

The fix is injected at the origin:

```
CDN --TLS--> nginx:8443 --WS--> ws-ping-inject:18444 --TCP--> sing-box:18443
```

After the HTTP 101, `ws_ping_inject.py` parses the server-to-client direction as
a WebSocket frame stream and injects an empty ping frame (opcode 0x9) every 25 s
**on a frame boundary**. The boundary matters: writing into a half-forwarded
frame desynchronises the stream permanently, and the symptom is identical to the
idle timeout — making the fix indistinguishable from the bug.

> The origin-side ping **takes effect for every CDN client without refreshing
> the subscription** — it lives on the data path, not in the config.

### Other hard constraints on this path

- **mux must be `h2mux`.** On VLESS+WS behind a CDN, sing-box clients using
  yamux/smux fail the handshake immediately with `context canceled`; mihomo with
  smux drops roughly every five minutes.
- **Keep mux concurrency at 4.** Two TCP connections head-of-line block on a
  lossy link; many more spread the mux across edges.
- **The origin port cannot be 443.** sing-box owns 443, and REALITY forwards
  every non-proxy connection verbatim to its handshake target, so nginx would
  never see these connections. The CDN pulls over HTTPS only from 443 / 2053 /
  2083 / 2087 / 2096 / 8443, and the installer accepts only those — picking
  another produces a vhost that works when tested locally on the server and 522s
  through the CDN, which reads like an origin failure.
- **The origin-pull port is opened only to CDN ranges**, and that range list is
  **fetched**, never typed from memory (§7).

---

## 6. Edge IP selection: burned twice by ranking on handshake RTT

Choosing CDN edge IPs went wrong twice, on two different lines, the same way:

| Line | Fastest handshake in the field | Its end-to-end result |
|---|---|---|
| Mobile | `104.19.63.243` at **61 ms** | **0.16 Mbps** throughput |
| Unicom | `104.20.29.23` at **89.5 ms** (2.4× faster than the rest) | **108 KB/s — last place**, 3× slower than the 220 ms group |

The reason is simple: **a handshake RTT measures only client → edge, while the
origin is at the other end — it misses the entire edge → origin leg.**

> **On any multi-hop path, a metric for one hop can point the opposite way.**
> Single-leg metrics are for screening only; ranking must be end to end.

`scripts/pick-cf-ip.py` works that way: handshakes only discard what is
unreachable (on one Unicom line, only 51 of 329 sampled addresses completed a
handshake — 85% blocked), and ranking always runs real traffic, cross-polled.

### Selection criteria: success rate first, then network spread — never speed

Within one success-rate tier, throughput ranking is usually noise: the 5/5 tier
measured 284–309 KB/s median while **a single node's own variation was
295–318** — the within-group spread equalled the between-group difference, so
the ordering meant nothing. `pick-cf-ip.py` computes both and tells you outright
when noise dominates.

### Before dropping an IP you already use

**Edge assignment follows the path, not the address.** The same `104.17.48.94`
lands in Hong Kong for a Mobile line (60 ms handshake) and in the United States
for a Xi'an Unicom line (219 ms). Dead on your line does not mean dead on
someone else's.

```bash
# Run this on the line you want to optimise, not on the server
python3 scripts/pick-cf-ip.py --domain example.com --interface en0
```

---

## 7. How to measure: five rules

Not about any single failure — about **how to measure, and how to judge whether
the measurement can be trusted.** Every one of these was learned the hard way.

### 7.1 Get out of your own TUN first

**Symptom:** `ping` to a Los Angeles server reports **0.589 ms** and `nc` to 443
takes 0.02 s. It looks like a local rack — it is your own TUN intercepting the
packets and looping them back locally. **All such data is void, and it will
point you in exactly the wrong direction.**

`curl --interface en0` is **not enough**:

- Name resolution still goes through the TUN and returns a fake-ip (198.18.x.x),
  which fails instantly (exit 7) rather than reporting anything.
- A local `HTTP_PROXY=127.0.0.1:7890` pushes https into a port that **may not be
  listening at all** — also an instant failure that looks like "the line is
  down".
- `nc -s <local-ip>` **does not work**: it binds the source address without
  changing routing, so the traffic still goes through the TUN and tells you
  everything is fine.

```bash
# Correct: bypass the env proxy, force the physical NIC, then confirm the exit
# IP belongs to your ISP and not to your node
curl --noproxy '*' --interface en0 http://ip.3322.net
```

`pick-cf-ip.py --interface` uses `IP_BOUND_IF` (macOS) / `SO_BINDTODEVICE`
(Linux), which really changes routing rather than just binding a source address.

**ICMP is intercepted too.** One `ping` reported 1.5 ms where the real TCP
handshake was 220 ms.

### 7.2 The log level decides what "no logs" means

With server `log.level` at `warn`, **successful connections write nothing at
all.**

A real misreading: "no Hysteria2 in the last hour of logs" was taken as "the
phone is not using Hysteria2". It actually meant "**Hysteria2 reported no
errors**" — the opposite conclusion.

```bash
jq -r .log.level /etc/sing-box/conf/00_log.json   # level first, then read counts
```

For *usage* rather than *errors*, use kernel counters, not logs:

```bash
iptables -t nat -L ANYREALITY_ALTPORT -v -n   # pkts/bytes are real traffic
ss -nt state established | grep -c 18443
```

### 7.3 On a jittery link, prove the difference is not noise

Cross-border mobile links have a standard deviation up to 1.05 s. **A single A/B
run on such a link will almost certainly deceive you.**

Method: **cross-polling** (A→B→C→D repeatedly, not all of A then all of B), then
compare the **within-group spread** against the **between-group median
difference**:

| Case | Within-group spread | Between-group difference | Verdict |
|---|---|---|---|
| mux parameters A/B | **10.47 Mbps** | 7.85 Mbps | ❌ within > between: **meaningless**, changed nothing |
| Hong Kong vs Los Angeles edges | 0.09–0.46 s | 0.39 s | ✅ far above the noise floor, acted on it |

That mux round first measured "variant D is 6× the current throughput" and
nearly got shipped. Three more rounds showed one configuration's own variation
exceeded the difference between configurations — **changing anything on that
basis is mistaking noise for signal.**

### 7.4 Measure end to end, not one leg

See §6. The same mistake repeated on two lines and cost two wrong edge-IP
selections.

### 7.5 Verify runtime state, not the file you edited

This project has been caught by the same pattern in three different places:

| What changed | ❌ Not proof it took effect | ✅ Correct verification |
|---|---|---|
| nginx config | `nginx -t` passes, `reload` succeeds | `nginx -T \| grep <key>` |
| sysctl | It is written in the file | `sysctl -n <key>` |
| Profile structure | `sing-box check` passes | Actually start it + `check_profile.py` |
| Rule-sets | The file exists | `type` must be `inline`; remote count 0 |
| Retiring a protocol | The server config changed | `grep -c <old protocol> <config>` is 0 **and** every deploy script and doc was searched |
| Edge IPs | The handshake is fast | Run it end to end |

`nginx -t` only says the files on disk parse — and it keeps saying so after a
`sites-enabled` symlink has been replaced by a stale regular file. `nginx -T`
prints what the process actually holds.

### 7.6 Triage order

```
1. Which network am I on?        curl --noproxy '*' --interface en0 http://ip.3322.net
2. Did I bypass the TUN?         the exit IP must be the ISP's
3. What is the log level?        decides how to read "no logs"
4. Did packets reach the server? nat counters / conntrack, not logs
5. Which hop is slow?            split it: TCP → TLS → TTFB → end to end
6. Is this difference noise?     cross-poll; within-spread vs between-difference
7. Did I verify runtime state?   see the table in 7.5
```

---

## 8. Kernel parameters: one file, and only effective values count

`/etc/sysctl.d/` is **read in filename order and later files silently override
earlier ones**. One host audited during this project had five `99-*.conf` files
and fourteen keys defined more than once — including
`net.ipv4.tcp_congestion_control` in two of them.

"I edited `99-bbr.conf` and nothing happened" was therefore **inevitable**, with
nothing visible to explain it. Same shape as an nginx `sites-enabled` symlink
replaced by a regular file: **the edit looks applied and is not.**

So the installer now:

- writes **one** `/etc/sysctl.d/99-anyreality.conf` and removes the
  `99-bbr.conf` / `99-swap-tuning.conf` it used to write itself;
- verifies **effective values** with `sysctl -n` immediately afterwards and
  warns on any mismatch;
- re-verifies on every health check via `scripts/check_sysctl.py`.

What is tuned and why:

| Parameter | Value | Rationale |
|---|---|---|
| `tcp_congestion_control` / `default_qdisc` | bbr / fq | Baseline for lossy cross-border links |
| `tcp_slow_start_after_idle` | 0 | Otherwise the congestion window resets after every idle period and each burst restarts in slow start — very visible at 200 ms |
| `rmem_max` / `wmem_max` | 32 MB | Cross-border BDP: 200 ms × 1 Gbps ≈ 25 MB. Default buffers cap throughput before the link does |
| `tcp_keepalive_time` / `_intvl` / `_probes` | 60 / 15 / 4 | Domestic CGNAT reclaims idle TCP mappings in 30–90 s. Slower than that and idle tunnels come back dead |
| `tcp_retries2` | 8 | The ~15 min default keeps a hopeless connection occupying a client slot on lossy paths |
| `tcp_notsent_lowat` | 128 KB | Keeps interactive traffic from queueing behind a bulk transfer already in the kernel |
| `netdev_max_backlog` | 16384 | Hysteria2 is UDP: too small a queue drops datagrams under load, and the loss looks like a bad path |

> **Add new parameters to that file**, confirm with `sysctl -n <key>`, and
> **do not create another `99-*` file** — that is how the trap gets dug again.

---

## 9. Domestic direct routing: what is slow is the routing, not the node

The most common complaint is "after importing the subscription, Taobao, WeChat,
Bilibili and online banking all got slow". That is almost never the node:

**In TUN mode there is no global/direct switch — whether traffic uses the proxy
is decided entirely by rules.** Incomplete rules send domestic traffic overseas,
and a domestic site routed through Los Angeles is "slow" for reasons that have
nothing to do with node bandwidth.

The shipped profile has four layers plus two details that are easy to miss:

1. Private networks direct
2. Ad blocking
3. **Domestic direct**: the inline safety net (~60 high-traffic suffixes,
   dependent on no download) → `geosite-cn-extra` (this repo's domestic-CDN
   supplement) → `geosite-cn`
4. Everything else through the node

**Detail one: IP rules need `action: resolve` in front of them.** Clients send
domains, and sing-box will not resolve one just to evaluate an IP rule —
`route.default_domain_resolver` does not change that either, it only decides
*which* resolver is used once something asks. Without a resolve action a
`geoip-cn` rule is **present, valid, and can never match**.
`check_profile.py` enforces that ordering.

The converse also matters: `resolve` replaces the destination domain with an
address for every connection after it, so the generator emits it **only when
something downstream really matches on IP**, never "just in case".

**Detail two: the Cloudflare challenge widget is AAAA-only.**
`brunhild.challenges.cloudflare.com` has had AAAA records only for a long time.
Under a global `ipv4_only` strategy it resolves to nothing and CAPTCHA pages
spin forever.

That fix **must live on the DNS layer**: in TUN mode the application resolves the
name before it ever opens a socket, so a route rule never gets a say — the
lookup already came back empty. The profile carries a DNS exemption for
`challenges.cloudflare.com` (`prefer_ipv4`), and `check_profile.py` verifies it
is still there.

---

## 10. Rules for maintaining this

**① Opening an inbound port means opening it for the right protocol.**
`ufw allow 443` opens TCP only. Behind a TCP-only rule Hysteria2 listens happily
and is unreachable from every client, with no server-side symptom. The installer
and the health check now both check the protocol explicitly.

**② Connection parameters are locked once configured — they are not something to
"rotate periodically".** uuid, passwords, ports, keys, tokens, public_key,
short_id: do not change them for "tidying up", "security best practice" or
"consistency". Change them only when ① a measured performance problem requires
it, ② there is evidence the credentials leaked, or ③ the user asks. Past
rotations solved nothing and caused mass client disconnections.

**③ Server and subscription change together.** `password` / `listen_port` /
`server_name (SNI)` / `short_id` must match between the server inbound and the
client profile. Changing one side means instant failure with a misleading error.

**④ Changing live config means verify → take effect → roll back on failure.**
`sing-box check` does not catch runtime errors: a config once passed `check` and
then died at startup (a `detour` pointing at an empty outbound).
`rebuild-profiles.sh` therefore builds into a temp directory, runs the structural
validator, then runs `sing-box check`, and publishes only if all of it passes —
otherwise the previous working profile stays.

**⑤ Every process on the data path must be in the inventory and the health
check.** `ws-ping-inject` ran on the CDN data path for a long time without
appearing in any inventory, and during an outage it was invisible — nobody looks
at a component they do not know exists.

**⑥ A static fallback must be a symlink, not a copy.** A hand-copied fallback
profile drifted silently for over a month; when it finally took over, clients
"updated successfully" and could then connect to nothing — worse than no
fallback, because it looked like success.

---

## Appendix: one full health check

```bash
# On the server
anyreality-resi-stack-healthcheck

# Covers: listener + firewall for each of the three paths, NAT redirect count,
# ws-ping-inject liveness, whether nginx's RUNNING config carries the relay
# path, structural invariants of the published profile, rule-set freshness,
# effective kernel parameters, certificate expiry, backup freshness.
```

Individual checks:

```bash
python3 /usr/local/lib/anyreality-resi-stack/check_profile.py \
  /etc/anyreality-resi-stack/files/profile.json \
  /etc/anyreality-resi-stack/files/profile.yaml
python3 /usr/local/lib/anyreality-resi-stack/check_sysctl.py
```

See also: [Deployment](DEPLOYMENT.md) · [Client import](CLIENTS.md) ·
[Routing](ROUTING.md) · [Troubleshooting](TROUBLESHOOTING.md) ·
[Operations](OPERATIONS.md)
