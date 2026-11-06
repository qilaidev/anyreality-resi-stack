# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

> **China-network hardening & selective WARP release.** One path is not enough,
> the previous default protocol could not be expressed by half the client
> ecosystem, and the shipped profile could deadlock a client at startup. All
> three are fixed here — plus three-ecosystem adaptive subscriptions (`profile.json` +
> `profile.yaml` + `profile.txt`) and server-side selective Cloudflare WARP
> WireGuard egress (`--with-warp` + auto-degrade watchdog).
> **Existing nodes must re-run the installer and re-import the client profile.**

### Added — Three-Ecosystem Subscription & Selective WARP Egress

- **Three-ecosystem adaptive subscription (`profile.json` + `profile.yaml` + `profile.txt`)**:
  `scripts/build_profile.py` now supports `--format uris`, generating a Base64-encoded
  multi-path URI bundle (`vless://` REALITY + alternate ports, `hysteria2://` +
  alternate ports + salamander + `pinSHA256`, `vless://` CDN WebSocket edge IPs, and
  Datacenter nodes) ordered by cold-start resilience. `subscription/_common.py`
  automatically serves `profile.txt` to Shadowrocket / v2rayN / v2rayNG / Streisand /
  V2Box / Loon / Quantumult X User-Agents and supports explicit
  `?format=singbox|clash|uris` query overrides on `/<TOKEN>/`.
- **Server-side selective Cloudflare WARP WireGuard egress & self-healing watchdog
  (`--with-warp`, `scripts/warp_egress.py`, `anyreality-resi-stack-warp`)**:
  Configures native `sing-box` WireGuard endpoint (`02_warp_endpoints.json`),
  `challenges.cloudflare.com` DNS AAAA preference (`05_dns.json`), and a strict
  10-stage route table (`03_route.json`) verified by C9 invariants
  (`warp_egress.py audit`). Solves AI/social ASN 403/Turnstile blocks and AAAA-only
  `challenges.cloudflare.com` deadlocks on IPv4-only VPSes while preserving 100%
  native residential IP egress for Google, Netflix, Disney+, TikTok, and banking
  (`EXCLUDE_DIRECT`). Includes `warp-watchdog.{service,timer}` to probe
  `127.0.0.1:10809` every 2 minutes, auto-degrading to `direct` after 3 failures and
  auto-recovering to `warp-ep` after 3 successes.
- **Expanded domestic CDN & platform rule-set (`data/geosite-cn-extra.json`)**:
  Expanded from 111 to 175 deduplicated Chinese mainland domain suffixes covering
  domestic cloud, AI, bank, logistics, travel, and CDN edges.
- **Hardened WebSocket ping injector (`scripts/ws_ping_inject.py`)**:
  Added `has_oversized_frame()` zero-buffer passthrough when a single WebSocket frame
  exceeds `MAX_FRAME` (16 MiB) so a large binary frame can never cause unbounded
  buffering and OOM-kill (`MemoryMax=128M`) the relay daemon; enabled `TCP_NODELAY`
  on both loopback sockets to eliminate 40 ms Nagle + delayed-ACK latency; added
  `WS_PING_CONNECT_TIMEOUT` (default 10s) and clean `wait_closed()` socket teardown.
- **REALITY `SHORT_ID` & SNI preflight, UDP/QUIC kernel buffers, dual-stack NAT, and
  fail-safe origin firewall**: Fresh installs now mint a random 8-byte hex `SHORT_ID`
  by default (customizable via `--short-id`, preserved across upgrades), and
  `phase_preflight()` verifies TLS 1.3 reachability to `${SNI}:443`; added
  `rmem_default`, `wmem_default`, `udp_rmem_min`, `udp_wmem_min`, `optmem_max`, and
  opportunistic `ethtool` GRO/GSO offload; mirrored alternate-port REDIRECT rules into
  `ip6tables -t nat` when available; restricted `CDN_ORIGIN_PORT` to both IPv4 and IPv6
  Cloudflare ranges with a pinned official CIDR fallback so a transient `curl` failure
  never opens the origin port to `0.0.0.0/0`; added C3 server-vs-profile drift and C9
  WARP route audits to `scripts/healthcheck.sh`.

### Changed — BREAKING

- **The default protocol is now `vless-reality` (VLESS + REALITY +
  xtls-rprx-vision), not AnyReality.** AnyTLS's padding is genuinely stronger and
  `--protocol anytls-reality` still installs it — but mihomo's `anytls` block has
  **no `reality-opts` field**, so `public-key` / `short-id` have nowhere to go and
  the node cannot be written into a Clash profile at all. The failure was
  invisible from the server: config valid, service green, `sing-box check`
  passing, sing-box users fine — and Clash users silently left with no primary
  node and no error to show for it. Client-kernel coverage is now the first
  selection criterion, ahead of speed.
  `build_profile.py` **refuses** to emit a Clash profile under
  `anytls-reality` rather than emitting a crippled one.
  (`--protocol vless-vision` remains accepted as the historical spelling.)

  **Upgrading does not change your protocol.** A host with an existing
  AnyReality inbound keeps it when the installer is re-run without an explicit
  `--protocol`, with a warning explaining the new default. Re-running is the
  documented way to update, so it must not be a way to lose every client that
  already imported the AnyTLS password. Pass `--protocol vless-reality`
  deliberately to switch — and re-import on every client afterwards.
- **Client profiles are generated, not templated.** `templates/singbox-client/*`
  and `templates/clash/*` client profiles are replaced by
  `scripts/build_profile.py`, which produces both formats from one params file.
  Two hand-maintained profiles for one topology drift, and the drift is only
  visible to whichever client family reads the file nobody re-checked.
- **`/etc/sysctl.d/99-bbr.conf` and `99-swap-tuning.conf` are folded into a
  single `99-anyreality.conf`** and removed. `/etc/sysctl.d/` is read in filename
  order and later files silently override earlier ones, so splitting settings
  across files makes "I edited it and nothing happened" inevitable. The installer
  now verifies effective values with `sysctl -n` after writing.

### Added

- **Three transport paths by default, raced by the client.** REALITY over TCP,
  **Hysteria2 over UDP** (`--no-hysteria2` to disable), and an optional
  **VLESS + WebSocket relay behind a CDN** (`--cdn-domain` / `--cdn-cert` /
  `--cdn-key`). Their failure causes are uncorrelated: REALITY dies to
  ClientHello interference, Hysteria2 to blanket UDP blocking, and the CDN path
  is the only one that survives a blackholed server IP. Full reasoning and
  measurements: `docs/*/CHINA-NETWORK.md`.
- **Hysteria2 with a pinned self-signed certificate.** The installer mints the
  certificate and pins it in the client profile (PEM for sing-box, SHA-256
  fingerprint for mihomo), so the UDP path needs neither a domain nor a
  client-side `skip-cert-verify`.
- **Alternate ports 2096/8880/40443** as iptables NAT REDIRECTs to the main port
  (`--alt-ports`, `--no-alt-ports`). Zero sing-box config change, and because the
  rewrite happens in `nat/PREROUTING`, UFW needs no rule for them — they also do
  not appear in `ss -tlnp`, which is expected. Interference is per-port and
  per-carrier and it moves: 443 was once the only usable port on a line where
  every high port was dead, and five weeks later on that same line 443 was three
  times slower than 8880.
- **`scripts/ws_ping_inject.py`** — the CDN closes a proxied WebSocket after
  ~100 s with no frames, and TCP keepalive cannot prevent it because it is
  hop-by-hop and terminates at the edge. The injector adds an application-level
  WebSocket ping every 25 s, on frame boundaries. Without it the symptom is a
  tunnel that dies at almost exactly 2m05s, over and over, which reads like a
  CGNAT or nginx timeout and is neither.
- **`scripts/check_profile.py`** — structural invariants that `sing-box check`
  cannot see: no remote rule-sets, the auto group's first member must be the path
  that works on the widest set of lines, no `connect_timeout`, no vision+mux, WS
  must use h2mux, no probe that interrupts live connections, `action: resolve`
  before any IP-based rule, no dangling group members, and the DNS exemption for
  the AAAA-only challenge host. Run by the installer, the rebuild script and the
  health check; `tests/test_profile_invariants.py` proves each check fires.
- **`scripts/pick-cf-ip.py`** — end-to-end CDN edge selection. Ranking by
  handshake RTT produced a confidently wrong answer twice (61 ms → 0.16 Mbps;
  89.5 ms → last place), because a handshake measures only client→edge while the
  origin is at the other end. Handshakes screen; ranking runs real traffic,
  cross-polled, and the script reports when the spread within one edge exceeds
  the difference between edges — i.e. when its own ranking is noise.
- **`scripts/check_sysctl.py`**, **`scripts/fetch-rulesets.sh`**,
  **`scripts/rebuild-profiles.sh`** (build → validate → `sing-box check` →
  publish atomically), **`scripts/altport-redirect.sh`**, and a weekly
  `refresh-rulesets.timer`.
- **One subscription URL now serves both ecosystems.** The server picks sing-box
  JSON or Clash YAML from the client's User-Agent, so a household mixing sing-box
  phones and Clash desktops needs one address, not two.
- **The subscription is now compressed** when the client offers `Accept-Encoding:
  gzip` (cached per profile version, correct `Content-Length` on HEAD). With the
  rule-sets inlined the profile is re-downloaded on every refresh over exactly
  the congested links this project targets: 585 KB becomes 84 KB on the wire.
- **`docs/zh-CN/CHINA-NETWORK.md` / `docs/en/CHINA-NETWORK.md`** — the core
  document: path design, port strategy and why a single measurement expires, the
  boot deadlock and its three defences, group ordering and probe parameters, the
  CDN idle timeout, edge-IP selection, kernel tuning, and a measurement
  methodology (bypass your own TUN, cross-poll, noise vs signal, verify runtime
  state and not the file you edited).
- Health-check coverage for every new component, including the per-protocol UFW
  check — `ufw allow 443` opens TCP only, and a Hysteria2 inbound behind a
  TCP-only rule listens happily while being unreachable from every client.

### Fixed

- **The client could refuse to start, and rebooting appeared to fix it.**
  sing-box downloads every `type: remote` rule-set *during* startup and a failure
  is `FATAL`. The download goes through the group named by `download_detour` —
  and on a cold start urltest has no measurements, so it uses its first member.
  Where that member is dead the kernel dies, the app restarts it, and it dies
  again; users report "the app quits the moment I open it". Every rule-set is now
  `type: inline`, the download happens weekly on the server, and a client boot
  makes no network request at all. Measured end to end: a 0.56 MiB profile,
  81 KiB gzipped, ~84 KB actually on the wire — against 280 KB across five
  requests before.
- **The server refused to start on sing-box 1.13.** The Cloudflare challenge
  exemption in `templates/singbox/05_dns.json` had a domain, an action and a
  strategy but no `server`, and the only DNS server entry had no tag — so
  sing-box exited with `initialize dns router: parse dns rule[0]: missing server
  field` before opening a single port. The file was valid JSON and passed every
  presence-based check; only running `sing-box check` against it says otherwise.
  Both example profiles and the rendered server config are now verified with the
  real binary, and `tests/test_routing_rule_order.py` asserts that every DNS rule
  names a declared server.
- **No profile can ask a client to skip certificate verification.** The
  Hysteria2 path pins the server certificate; `insecure` / `skip-cert-verify`
  are no longer emitted at all, and `check_profile.py` rejects them along with a
  pinned certificate that is not parseable PEM — sing-box *panics* on that rather
  than reporting a config error, which reads as "sing-box is broken".
- **The installer aborted at preflight on every re-run.** The official sing-box
  package ships a `sing-box@.service` *template* unit, which the foreign-unit
  guard flagged as a competing manager — so the second run of an installer
  documented as idempotent refused to start, on every real host. Templates
  manage nothing until instantiated; only enabled instances are refused now.
- **Template rendering silently skipped every token containing a digit.**
  `render_template` matched `@@[A-Z_]+@@`, which does not match
  `@@HY2_PASSWORD@@`, so the Hysteria2 inbound was written out with its
  placeholders intact and the render reported success. `sing-box check` caught
  it one phase later as a JSON parse error pointing at a `@`. The pattern now
  includes digits, and — more durably — both renderers now fail if any
  placeholder survives into the output.
- **The health check silently stopped half-way on a fresh install.** Under
  `set -o pipefail` an assignment inherits its command substitution's status, so
  a `find` over a backup directory that did not exist yet killed the script —
  and every check after that point simply never ran, with no indication. Those
  assignments are now tolerant, and an early exit reports itself instead of
  looking like "nothing to say". A fresh install also no longer FAILs for having
  no backup archive before the daily timer has ever fired.
- **`--purge-all` left state behind**: `/var/lib/anyreality-resi-stack` and
  `/etc/sysctl.d/99-anyreality.conf`, the latter still altering host kernel
  behaviour after the software was gone.
- `action: resolve` is now emitted **only** when something downstream actually
  matches on IP. It rewrites the destination for every connection after it, so
  adding it unconditionally changed what the node received.

## [Previous unreleased entries]

> **Routing-correctness release.** A group of rules that `sing-box check`
> accepted, the service ran with, and the log stayed clean about — while doing
> nothing. Existing nodes should re-run the installer (or port
> `templates/singbox/05_dns.json` and the client templates by hand) and re-import
> the client profile.

### Fixed

- **Cloudflare CAPTCHAs could never be solved through the node.** Cloudflare serves
  its challenge widget from `brunhild.challenges.cloudflare.com`, which has had
  **AAAA records only, no A record** for a long time (cross-checked against
  1.1.1.1 / 8.8.8.8 / 9.9.9.9). Both the server DNS config and the client profiles
  used `strategy: ipv4_only` with no exemption, so that host resolved to an empty
  result and the verification page span forever — with a single
  `lookup … : empty result` line in the error log as the only clue. This is the worst
  possible failure for this project's audience, since routing ChatGPT/Claude/banking
  through the node is exactly what puts you in front of CAPTCHAs.

  The exemption has to live in the **DNS layer** on both sides. In TUN mode — the
  mode this project recommends — the application resolves the hostname before it
  ever opens a socket, so a routing rule never gets a say: the lookup has already
  come back empty. `templates/singbox/05_dns.json` and both client templates now
  route the suffix with `prefer_ipv4` (use A when present, fall back to AAAA). The
  client route rule pinning it to the node is kept as well — it costs nothing and
  states the intent.

  On a node with **no IPv6 egress at all** this still cannot work; the health check
  now says so explicitly instead of leaving you to guess.

- **`geoip-cn` never matched domain traffic in the client profiles.** Clients send
  domains; sing-box does not resolve them just to evaluate an IP-based rule, and
  setting `route.default_domain_resolver` does **not** change that — it only decides
  *which* resolver is used once something asks. Verified empirically on sing-box
  1.13.14: with no `action: resolve` ahead of it, a `geoip-cn` rule never fired for a
  domain request; adding one made the same request match immediately. Domestic sites
  absent from `geosite-cn` were therefore detouring abroad. Both client templates now
  run `action: resolve` before the IP-based rules. Resolution still follows the DNS
  rules — confirmed by pointing a test domain at a blackhole resolver — so domestic
  names keep the domestic resolver and foreign names stay resolved over the node. No
  poisoning is introduced.

- **Removed a dead `action: resolve` from the server route template.** It shipped
  from v1.0.0 targeting `api.openai.com`, but the server's rule list ends right after
  it with `final: direct` — nothing ever consumed the resolved address, so it could
  not influence any routing decision. `api.openai.com` also publishes A records, so
  the `prefer_ipv4` fallback it implied never applied either. Dead config that reads
  as deliberate is exactly what misleads the next maintainer.

- **The "four independent providers" public-IP detection was effectively one.**
  `api.ipify.org`, `icanhazip.com` and `ipv4.icanhazip.com` all resolve into
  Cloudflare ranges — and the last two are the same service on the same addresses —
  so a Cloudflare incident took out three of the four fallbacks simultaneously. The
  list is now one entry per hosting provider: Google Cloud, AWS, Hetzner, Cloudflare.

- **`make redact` had been failing on `main` since 2026-08-03.** The 43-char
  base64url shape check exempted `snake_case` identifiers but not `kebab-case`, so
  Markdown heading anchors that happen to be exactly 43 characters were reported as
  unknown secrets — 8 permanent violations, which is worse than no check at all
  because a genuine leak would scroll past in a wall of known-bad output. kebab-case
  now gets the same carve-out, for the same reason and with the same ~1e-10 collision
  odds. Mixed-case base64url is still scanned (verified: a real Reality-key-shaped
  string is still caught).

### Added

- Health check probes IPv6 egress and names the consequence: without it, Cloudflare's
  AAAA-only challenge widget cannot load and CAPTCHA pages spin forever. Warns rather
  than fails, since a node without IPv6 is otherwise fine.
- `tests/test_routing_rule_order.py` asserts **which layer a fix lives on** and
  **relative rule order** — the only things that distinguish a working rule from a
  dead one here. Covers the client and server DNS exemptions, CF-challenge pinned to
  the node ahead of the resolve rule, resolve-before-IP-rules, and the absence of a
  dead resolve on the server. Every assertion was fault-injected to confirm it fails
  when the corresponding fix is reverted.
- `docs/zh-CN/TROUBLESHOOTING.md` / `docs/en/TROUBLESHOOTING.md`: a Cloudflare CAPTCHA
  section that separates the two independent problems people conflate — *appears often*
  (exit ASN reputation) versus *never completes* (AAAA-only widget) — with the
  diagnostic commands for each, and a warning that plain `curl` returns 403 against
  Cloudflare regardless of IP health, so it cannot be used as evidence.

### Changed

- Documentation now verifies egress with `checkip.amazonaws.com` instead of
  `api.ipify.org`. The latter is Cloudflare-hosted, so it reports misleading results
  the moment any Cloudflare-related split routing is in play, and this project already
  documented it as frequently blocked or rate-limited.

### Notes

- The client-side `action: resolve` rule was briefly measured as a 2.7x slowdown for
  first contact with foreign domains and nearly reverted. That number came from running
  the two configurations **sequentially**, which on a trans-Pacific link measures jitter,
  not configuration. Re-measured with both clients running **concurrently** and
  alternating request order: 0.699 s without vs 0.681 s with — 0.97x, i.e. no
  difference. The rule stays. The rationale and the measurement are recorded in
  `tests/test_routing_rule_order.py` so this is not re-litigated with another
  sequential benchmark.
- The Clash templates were reviewed and deliberately left unchanged.
  `GEOIP,CN,DIRECT,no-resolve` already states the same trade-off explicitly, and domain
  traffic is handed to the proxy by name for the server to resolve — so `ipv6: false`
  does not strand the challenge widget there.

## [2.1.1] — 2026-08-03

> **Documentation release.** No installer, protocol, or runtime behavior changes. Existing nodes do not need reinstall or client re-import.

### Changed

- **README protocol scorecard (China-region best-pick)**: bilingual side-by-side scores with decision tree, explicit weights (last reviewed 2026-08), client matrix, migration steps, boundaries, and upstream-tracking commitment; VLESS path marked stagnant; FAQ/DEPLOYMENT/COMPARISON/llms.txt aligned.
- **SEO/GEO doc pass**: restructured bilingual README opening (what/why/who, quick start with dry-run, features, use cases, limits, GitHub About/topics); deduped mid-page sections; llms.txt entity card; FAQ one-liners; pyproject description polish.

## [2.1.0] — 2026-07-28

> **Production-readiness release.** No breaking changes to the protocol, the
> secrets layout, or already-imported clients. Re-running the installer on an
> existing host is the upgrade path: it reuses `secrets.env`, creates the
> `anyreality-sub` service account, moves the subscription services onto it,
> installs the logrotate policy and the operator tools, and leaves the sing-box
> keys untouched. Nothing needs to be re-imported on clients.

### Added

- **Operator tooling installed onto the node itself**, so an incident does not require a repo checkout. `scripts/healthcheck.sh` → `/usr/local/sbin/anyreality-resi-stack-healthcheck` is a read-only check covering the sing-box service and restart count, `sing-box check`, the inbound port actually listening, the subscription service and `/healthz`, TLS certificate expiry, the profile file existing, backup freshness/failure, whether an off-box backup hook is configured, root filesystem usage, `box.log` size, clock sync, UFW, and `secrets.env` permissions. It exits non-zero when the node is degraded, so `*/10 * * * * … --quiet` in cron is a complete alerting setup.
- `scripts/rotate-sub-token.sh` → `/usr/local/sbin/anyreality-resi-stack-rotate-sub-token` rotates the subscription token in place and rolls back automatically if the service does not come back healthy. The subscription URL is a credential served over plain HTTP; previously the only response to a leak was a full reinstall.
- **Log rotation for sing-box.** `00_log.json` writes to `/etc/sing-box/logs/box.log` with no size bound — at `level=error` it is normally tiny, but any persistent fault turns it into the fastest way to fill a small VPS disk, taking journald and the backup timer down with it. `phase_logrotate` installs `/etc/logrotate.d/sing-box` (daily, immediate rotation past 20 MiB, 7 compressed generations, `copytruncate`) and validates it with `logrotate -d`.
- [`docs/zh-CN/OPERATIONS.md`](docs/zh-CN/OPERATIONS.md) / [`docs/en/OPERATIONS.md`](docs/en/OPERATIONS.md): pre-launch checklist, health checks and alerting, log/disk bounds, backup verification/off-box copies/restore drills, rollback paths, token rotation, enabling HTTPS for the subscription endpoint, and the remaining boundaries (NIC-level accounting, single host, single user).
- `tests/test_config_validation.py` covers the new environment parsing, and `tests/test_leaf_accounting.py` locks the "accounting failure must not break the endpoint" behaviour.
- **Optional TLS for the subscription endpoint.** The subscription URL is a credential — the profile behind it contains the node password — and over plain HTTP anyone on the path can read both. `TLS_CERT_FILE` / `TLS_KEY_FILE` (or `--sub-tls-cert` / `--sub-tls-key` at install time) now serve it over HTTPS with a TLS 1.2 floor, using nothing but the standard library. The installer grants the service account group-read on the key material, `phase_verify` and the health check switch to HTTPS automatically, and the health check additionally fails when the certificate expires within 7 days — expiry is otherwise a silent outage where every client refuses the subscription while liveness probes stay green.
- **Off-box backup hooks.** Any executable in `/etc/anyreality-resi-stack/backup-hooks.d/` is called with the verified archive path, so an `rclone`/`scp`/`restic` one-liner turns local-only backups into real disaster recovery. A failing hook fails the backup run (and therefore the health check) because an off-box copy you believe exists but does not is the dangerous case; the local archive is kept regardless. A non-executable `10-offsite.sh.example` documents the contract on the box, and the health check warns when no hook is configured.
- `tests/test_endpoints.py` boots the real leaf server on an ephemeral port and drives it over HTTP — the request path, token check, usage-card headers, and traversal guard had no coverage at all before. `tests/test_common_serving.py` covers path safety, atomic writes, and the TLS context builder.
- **Client profiles now ship with complete routing rules.** The generated sing-box profiles previously only had an `ip_is_private → direct` rule and sent *everything* else through the node — which is unusable in TUN mode, where there is no global/direct toggle and domestic traffic silently detours abroad. Both `client-single.json.tmpl` and `client-dual.json.tmpl` now render a four-layer stack: baseline (`sniff`, `hijack-dns`, private-direct), ad/tracker `reject`, China-direct, and a fallback that rejects UDP/443 before sending the rest to the node. The Clash templates gain the matching ad-block rule and inline safety net.
- China-direct is deliberately two-tier: an inline ~60-entry `domain_suffix` safety net is evaluated *before* the remote `geosite-cn` / `geoip-cn` rule sets. The rule sets are downloaded from GitHub, which is commonly unreachable at first start — when that download fails the set is empty and every domestic site gets proxied. The inline list needs no network request, so high-traffic domestic services stay direct regardless. `download_detour` routes rule-set downloads through the node.
- Client profiles now include a DNS section that splits resolution (domestic names via `223.5.5.5`, everything else over DoT through the node) plus `experimental.cache_file` for rule-set persistence.
- [`docs/zh-CN/ROUTING.md`](docs/zh-CN/ROUTING.md) / [`docs/en/ROUTING.md`](docs/en/ROUTING.md): the routing model, how to add or remove domains, how to change the defaults, and how to verify a domain really goes direct without being fooled by a TUN client hijacking the test.
- `SECURITY.md` documents the subscription URL exposure surface: the profile is served over plain HTTP on :80 and contains the node password, so the URL is a credential; anything placed in `FILE_DIR` is served under the same token path, so backups must not go there.
- `tests/test_content_disposition.py` locks the `Content-Disposition` header shape.

### Fixed

- **The subscription servers no longer run as root.** They are the only component in this repo listening on a public port, and they had no reason to hold root. Both units now run as the unprivileged system user `anyreality-sub` with `AmbientCapabilities=CAP_NET_BIND_SERVICE` and a matching `CapabilityBoundingSet`. systemd reads the EnvironmentFile as root *before* dropping privileges, so `secrets.env` stays 0600 root-only and is unreachable from the HTTP server itself. Re-running the installer migrates an existing host in place.
- **`safe_target_path` accepted `..`.** pathlib does not normalise dot entries — `Path("..").name` is `".."` — so the separator check let `FILE_DIR/..` through. Today the caller's `is_file()` guard makes it a 404 rather than a traversal, but the guard was load-bearing by accident; dot entries and hidden files are now rejected outright. Caught by a new test, not in production.
- **The two subscription servers no longer carry duplicate copies of the same code.** Routing, environment parsing, path safety, `Content-Disposition`, and the HTTP server lived twice, which is how they drifted (the leaf and aggregator health payloads had different `ensure_ascii` handling). The shared half moved to `subscription/_common.py`, which both import; `current_usage()` and `refresh_usage_cache()` collapsed into one function with a `force_refresh` flag. Deployment is unchanged — the file ships next to the servers and each anchors `sys.path` on its own directory.
- **Backup archives are now verified before old ones are rotated away.** The script lists the archive with `tar -tzf` and asserts it actually contains `etc/sing-box/conf/` and `etc/anyreality-resi-stack/`; a failure deletes the bad archive and exits non-zero instead of silently rotating out the last good backup in its favour. Archives also no longer carry `/etc/sing-box/logs`, which the header comment already claimed was excluded.
- **A bad EnvironmentFile no longer produces an endless silent crash loop.** Both subscription servers parsed environment variables with bare `os.environ[...]` / `int(...)`, so a missing `TOKEN` or a typo'd `PORT` surfaced as a raw traceback under `Restart=always` with no indication of which variable was wrong. Every variable is now parsed with range checks and exits 2 naming the offending variable; the servers also warn at startup when the `DEFAULT_TARGET` profile is missing, when `INTERFACE` does not exist under `/sys/class/net`, and when a port bind fails. `REMOTE_STATUS_URL` is rejected unless it is `http(s)` — `urlopen` would otherwise accept `file://` and read a local path.
- **Usage accounting can no longer take the subscription endpoint down.** `update_usage_state()` ran in the request path and propagated `OSError` from the state write, so a full or read-only `/var/lib` turned every profile fetch into a failed response. Serving the profile is the primary job; a persistence failure now degrades to "the counter stops moving".
- **`Restart=always` units can no longer be parked permanently.** With systemd's default rate limit (5 starts / 10 s) a transient fault could leave sing-box — the only proxy on the box — in a failed state that nothing recovers from. All three units set `StartLimitIntervalSec=0`. The subscription units additionally gain `ProtectKernelTunables`, `RestrictRealtime`, `RestrictSUIDSGID`, `LockPersonality`, and `SystemCallArchitectures=native`.
- **Public IP detection is no longer a single point of install failure.** `api.ipify.org` is blocked or rate-limited often enough that installs on fresh hosts fell through to a vague warning and a client profile rendered without a server address. Detection now tries four independent providers with a 5 s timeout each and validates the result is an IPv4 address.
- A flag given without its value (`--sni` as the final argument) died with a bare `$2: unbound variable` from `set -u`. The parser now names the flag.
- **`tests/` was not actually covered by the project's lint configuration.** The ruff settings lived in `subscription/pyproject.toml`, so files under `tests/` had no configuration in scope and were linted with whatever default rule set the installed ruff version happened to ship — CI and local runs disagreed, and a ruff release could break `main` with no code change (it did). The configuration moved to a repo-root `ruff.toml` covering both trees, the CI install is pinned, and the four issues this immediately surfaced in previously-unlinted test files are fixed.
- `scripts/redact.sh` no longer reports long snake_case identifiers as leaked secrets. The 43-character base64url shape it looks for also matches any descriptive function or test name, which pressures contributors into renaming good code or padding the allowlist with non-secrets — both of which erode the gate. Single-case snake_case is now excluded: a Reality key is 43 random base64url characters, so the odds of one landing entirely in `[a-z0-9_]` (or `[A-Z0-9_]`) with well-formed underscores are roughly 2e-10. Mixed-case strings are still scanned, and a randomly generated key is still caught.
- `uninstall.sh` removes the new `/usr/local/sbin` operator tools and `/etc/logrotate.d/sing-box`.
- `Content-Disposition` now emits a plain ASCII `filename="…"` alongside the RFC 5987 `filename*=UTF-8''…` form, and percent-encodes the latter. Clients that cannot parse the header invent a numeric snowflake id for the imported profile; the previous value omitted the fallback and left non-ASCII names unencoded.
- `uninstall.sh` no longer aborts partway through. Two `[[ -f … ]] && rm …` loop bodies returned non-zero when the last candidate file was absent — the normal case — which `set -Eeuo pipefail` turned into an aborted uninstall that left UFW rules and the fail2ban jail behind.
- `uninstall.sh` now removes the UFW rule for the port actually configured in `/etc/sing-box/conf` instead of assuming 443, and deliberately leaves SSH rules alone.
- `--dry-run` works on a host that already has `secrets.env`. The reuse path returned without defining the template variables, so the next phase died with an unbound-variable error; dry-run now exports obvious placeholders instead of reading real secrets.
- `phase_firewall` no longer risks locking you out. `--ssh-port N` only tells UFW which port to keep open — it does not move sshd (that is `--harden-ssh`) — so passing a port sshd was not listening on fenced off the real one at `ufw --force enable`. The ports sshd is actually bound to are now always allowed, with a warning.
- A failing `--harden-ssh` phase is no longer swallowed by a trailing `|| true`.

## [2.0.0] — 2026-07-19

> **Project renamed to `anyreality-resi-stack`** (formerly `reality-resi-stack`). GitHub automatically redirects old repository URLs, so existing `curl | bash` install commands keep working. Runtime filesystem paths (`/etc`, `/var/lib`, `/usr/local/lib`, `/var/backups`), systemd unit names, the backup script/archives, and the environment variable (now `ANYREALITY_RESI_STACK_REF`, with the legacy `REALITY_RESI_STACK_REF` still honored) are all renamed to the `anyreality-resi-stack` prefix. Upgrading a v1.x host runs a migration phase (`phase_migrate_legacy_paths`) that moves the old `reality-resi-stack` directories to the new prefix and retires the old backup unit, so existing secrets, usage state, backups, and therefore already-imported clients are preserved.
>
> **Breaking — default protocol changed.** Fresh installs now default to **AnyReality (AnyTLS + Reality)** instead of VLESS + Reality + xtls-rprx-vision. Existing servers keep their current protocol until the installer is re-run. AnyReality is sing-box-only; if you rely on Clash/mihomo clients, install (or re-run) with `--protocol vless-vision` to stay on the legacy protocol. Because AnyReality authenticates with a password rather than a UUID/flow and the default subscription file changed from `profile.yaml` to `profile.json`, clients must be re-imported after switching protocols.

### Changed

- **AnyTLS + REALITY (AnyReality) is now the default protocol.** New installs deploy a sing-box `anytls` inbound fronted by Reality, authenticated with a per-server password (`ANYTLS_PASSWORD` in `secrets.env`). AnyTLS's custom padding hardens against TLS-in-TLS fingerprinting while Reality keeps the certless server camouflage. Still no domain or TLS certificate required.
- The default subscription profile is now a full sing-box client config served as `profile.json` (mixed inbound on `127.0.0.1:2080`, AnyReality outbound, domain-based routing in dual-node mode); the legacy Clash `profile.yaml` is served only under `--protocol vless-vision`.
- Runtime layout renamed to the `anyreality-resi-stack` prefix: `/etc/anyreality-resi-stack`, `/var/lib/anyreality-resi-stack`, `/usr/local/lib/anyreality-resi-stack`, `/var/backups/anyreality-resi-stack`, `/opt/anyreality-resi-stack`, the `backup-anyreality-resi-stack.sh` script and `anyreality-resi-stack-*.tar.gz` archives, and the `anyreality-resi-stack-backup` systemd units. A new `phase_migrate_legacy_paths` installer phase migrates existing `reality-resi-stack` hosts in place; `uninstall.sh` also cleans up either prefix.

### Added

- `--protocol anytls-reality` (default) / `--protocol vless-vision` (legacy) selects the inbound protocol. VLESS + Reality + xtls-rprx-vision remains fully supported for Clash/mihomo users, which cannot parse AnyReality.
- AnyReality templates: `templates/singbox/11_anytls-reality_inbounds.json.tmpl` (server inbound), `templates/singbox-client/anytls-outbound.json.tmpl`, and full sing-box client configs `templates/singbox-client/client-single.json.tmpl` / `client-dual.json.tmpl` (dual-node smart routing via sing-box `route` rules).
- Installers predating AnyReality mint and append an `ANYTLS_PASSWORD` to an existing `secrets.env` on re-run, so switching to `--protocol anytls-reality` works without regenerating the UUID or Reality keypair. Re-running with a different protocol drops the stale inbound and profile file to avoid port collisions or format mismatches.

### Fixed

- Leaf subscription accounting now samples interface counters while holding the state lock, preventing concurrent requests/background polling from applying stale samples out of order.
- Aggregator usage cache writes now use per-thread temporary files plus atomic replace, avoiding `.tmp` collisions during concurrent refreshes.
- Backup archives now exclude hidden runtime `.tmp` state/cache files and place `manifest.txt` at the archive root.
- Leaf subscription accounting now keeps usage fresher by sampling in the background every `USAGE_POLL_INTERVAL_SECONDS` seconds instead of only updating when a client pulls the subscription URL.
- Leaf subscription accounting now supports provider billing reset days via `BILLING_CYCLE_DAY`, so plans that reset on the 11th do not roll over on the 1st by mistake.
- Leaf subscription accounting now counts bytes already present in the current boot on first state creation by default (`COUNT_CURRENT_BOOT_ON_INIT=true`), while still supporting baseline-only mode and `USAGE_OFFSET_BYTES` calibration.
- Leaf accounting now carries usage forward across reboots or NIC counter rollovers by adding the new boot's current counter instead of silently dropping it.
- Aggregator subscription accounting now refreshes the leaf status cache in the background via `REMOTE_POLL_INTERVAL_SECONDS`, keeping usage cards warm even before the next client request.
- Re-running the installer with an existing `secrets.env` re-exports the reused UUID, Reality keys, subscription token, and short ID before rendering templates.
- `--with-subscription` and `--with-aggregator` are now mutually exclusive, and aggregator installs fail early unless the residential-node template variables are provided.

### Added

- `ANYREALITY_RESI_STACK_REF` lets remote-piped installs fetch a specific branch or tag while defaulting to `main`.
- Standard-library `unittest` coverage for leaf accounting and aggregator cache fallback, wired into `make test` and GitHub Actions.
- `make mdcheck` now falls back to `npx --yes markdown-link-check` when the binary is not installed globally, retries transient link-checker failures once, and GitHub Actions runs the same Markdown link gate.

### Security

- Aggregator leaf-status polling now caps each remote status response with `MAX_REMOTE_STATUS_BYTES` (default 64 KiB) before parsing JSON.
- Subscription systemd units now use basic sandboxing (`NoNewPrivileges`, `PrivateTmp`, `ProtectHome`, `ProtectSystem=strict`) and only keep `/var/lib/anyreality-resi-stack` writable.
- Config backups now exclude runtime usage/cache state, set backup directory permissions to `700`, and write archives as `600`.

## [1.0.3] — 2026-05-19

### Added (Documentation)

- **`llms.txt`** — AI-search-engine index covering what the toolkit does, what it does NOT do, common questions ("Why is Telegram slow on residential IP?", "Why does OpenAI block my data-center VPS?"), and long-tail search phrases (residential IP VLESS, ChatGPT 住宅 IP 出口, Telegram 住宅 IP 卡顿, etc.).
- **README — FAQ section** with 7 Q&As covering the residential-vs-data-center dichotomy, idempotent re-runs, Reality-no-domain, 3x-ui/XHTTP-Installer comparison, and GPL-3.0 implications.
- **README — Keywords block + nav row** (Release / Docs / llms.txt / Changelog / Issues).

### Notes

Documentation-only release. Installer behavior is unchanged from v1.0.2; users running v1.0.2 do not need to re-deploy.

## [1.0.2] — 2026-05-17

### Added

- `phase_preflight` now refuses to proceed if it detects a pre-existing manual sing-box install (`/usr/local/bin/sing-box` present without the apt-managed `/usr/bin/sing-box`) **or** a foreign systemd unit matching `sing-box*.service` other than the default `sing-box.service`. Without this check, `apt install sing-box` silently adds a second binary and a second systemd unit alongside the existing manual install — both apparently inactive at install time, but the next reboot or any `systemctl start sing-box` would race against the user's working unit on ports 443/8443 and config paths. Caught the hard way by attempting v1.0.1 verification against a real production host that turned out to already host a manually-installed sing-box.

## [1.0.1] — 2026-05-17

### Fixed

- **Critical**: pinned `SINGBOX_APT_KEY_FPR` in `install/lib/singbox.sh` was a placeholder that did not match the real Sagernet GPG key bundle, causing **every real install to fail at `phase_install_singbox`** with a fingerprint-mismatch abort. Bug was not caught by `--dry-run` because dry-run intentionally skips the GPG check. Now pinned to the primary fingerprint `2C317FBD5D886B4E89BAE8DA6D9152172A2B2F0C` and verified against the live key file on Ubuntu 24.04 LTS.
- **Critical**: `phase_verify` ran live `systemctl` / `ss` / `sing-box check` calls in `--dry-run` mode, producing fake-looking failures and a non-zero installer exit even though nothing had been installed. Now correctly no-ops in dry-run.
- GPG verification logic now requires the pinned fingerprint to be **present anywhere in the bundle** rather than to be the first fingerprint — Sagernet bundles a primary key plus a signing subkey, so the first-fingerprint check was fragile against subkey rotation.

### Note for users of 1.0.0

v1.0.0 was withdrawn within an hour of publication due to the GPG fingerprint bug above — please use v1.0.1 or later. Sorry for the noise.

## [1.0.0] — 2026-05-17 (withdrawn)

Initial release. **Withdrawn** — see 1.0.1 changelog for the install-blocking bug found 30 minutes after publication.

### Added

- **Modular bash installer** (`install/install.sh` + 5 lib modules) for Ubuntu 22.04+ / Debian 12+. Phases: preflight → system tuning → sing-box install with verified GPG fingerprint → key generation → config render → systemd service → firewall (UFW + fail2ban) → optional SSH hardening → optional subscription server → backup timer → end-to-end verification. Idempotent, supports `--dry-run`, `--non-interactive`, `--config`.
- **VLESS + Reality + xtls-rprx-vision** server config templates (`templates/singbox/`) with no domain or TLS cert required.
- **Two Python subscription servers** (`subscription/leaf_server.py`, `subscription/aggregator_server.py`) — zero third-party dependencies, standard library only.
  - Leaf reads `/sys/class/net/<iface>/statistics/*_bytes` for monthly traffic accounting, emits `Subscription-Userinfo` / `Profile-Title` / `Profile-Update-Interval` headers.
  - Aggregator polls a leaf's `/status` endpoint, caches the result, and falls back to cached values during leaf outages (prevents "0 bytes used" jitter in client usage cards).
- **Smart routing Clash template** (`templates/clash/client-dual.yaml.tmpl`) for dual-node deployments:
  - Routes OpenAI / Anthropic / Claude / Google AI / Netflix / banking domains through the residential node (where residential-IP reputation is an asset).
  - Routes Telegram / Discord / messenger domains through the data-center node (avoiding the "residential IP soft-throttle" problem common to messenger services).
- **Hash-only secret denylist** (`scripts/.redact-denylist.sha256`) plus shape-based detector (`scripts/redact.sh`) — CI fails on any UUID, Reality key, or known-leaked IP.
- **Deterministic example generator** (`scripts/make-example.sh`) using RFC 5737 documentation IPs and sentinel UUIDs.
- **Daily systemd-timer backup** of configuration (excludes runtime state, secrets are mode-600).
- **Bilingual documentation**: 5 docs in `docs/zh-CN/` (DEPLOYMENT, SUBSCRIPTION, DUAL-NODE, TROUBLESHOOTING, CLIENTS) with English mirrors in `docs/en/`.
- **GitHub Actions CI**: shellcheck, shfmt, ruff, yamllint, jsonlint, plus the redact gate.

### Security

- sing-box apt repo signing key fingerprint pinned (`SINGBOX_APT_KEY_FPR`). Installer refuses to proceed on fingerprint mismatch — defense against supply-chain compromise.
- `secrets.env` written mode 600, owned by root.
- `.gitignore` aggressively blocks credential file patterns at the git layer; CI redact gate is the second line.

## Roadmap

### v1.1+ (community-demand-driven)

- Additional translations (Farsi, Russian, Arabic, Vietnamese, Turkish, Indonesian, Burmese, Spanish — based on issue requests)
- GitHub Pages site with proper sitemap + hreflang
- Asciinema cast of the installer flow

### v2 (not committed)

- Optional automated SNI rotation
- Optional Cloudflare WARP-style ECH support if sing-box stable adds it
- Three-node mesh aggregator
