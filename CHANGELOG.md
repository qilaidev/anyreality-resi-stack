# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-18

> **Initial open-source release.** Self-hosted multi-path `sing-box` edge gateway
> & WAN transport resilience stack (residential & data-center split-egress
> routing) for Ubuntu 22.04+ / Debian 12+, published with legal compliance
> boundaries in [`DISCLAIMER.md`](DISCLAIMER.md).

### Added — Multi-Path Transport & Core Installer

- **Modular, idempotent Bash installer (`install/install.sh` + `install/lib/{system,singbox,subscription}.sh`)**:
  Supports `--dry-run`, `--non-interactive`, `--config`, pinned tags via
  `ANYREALITY_RESI_STACK_REF`, and clean teardown (`--uninstall` / `--purge-all`).
  Preflight validates OS support, foreign `sing-box` unit conflicts, and TLS 1.3
  reachability to `--sni`.
- **Three uncorrelated transport paths raced by client `urltest`**:
  - **VLESS + REALITY + `xtls-rprx-vision` (TCP, default `--protocol vless-reality`)**:
    Selected as default because it is supported by both `sing-box` and `mihomo`/Clash
    client kernels (`mihomo`'s `anytls` block lacks `reality-opts`), avoiding silent
    missing-node failures. Mints an 8-byte hex `SHORT_ID` by default.
  - **Hysteria2 (UDP/QUIC, enabled by default, `--no-hysteria2` to disable)**:
    Mints a self-signed certificate and pins it directly in generated client
    profiles (PEM for `sing-box`, SHA-256 fingerprint for `mihomo`) without
    weakening TLS verification.
  - **Optional VLESS + WebSocket via Anycast CDN (`--cdn-domain`, `--cdn-cert`, `--cdn-key`)**:
    Survives direct-origin route blackholing, severe peering loss, or strict
    egress firewalls; enforces `h2mux` (`max_connections: 4`) and restricts
    `--cdn-origin-port` to standard HTTPS CDN pull ports (`2053/2083/2087/2096/8443`).
  - **Opt-in AnyTLS + REALITY (`--protocol anytls-reality`)**:
    Retained for `sing-box`-only client fleets requiring stronger custom frame
    padding (`build_profile.py` explicitly refuses to emit incomplete Clash YAML).
- **Kernel-level alternate port NAT redirection (`scripts/altport-redirect.sh`)**:
  Routes `2096 / 8880 / 40443` to the primary inbound port via dual-stack
  `iptables` / `ip6tables` `nat/PREROUTING` (`ANYREALITY_ALTPORT` chain), avoiding
  `sing-box` inbound duplication and mitigating per-port carrier QoS shaping.
- **Origin-side WebSocket frame-boundary keepalive (`scripts/ws_ping_inject.py`)**:
  Injects empty WebSocket `PING` control frames (opcode `0x9`) strictly on frame
  boundaries every 25 s to prevent ~100 s CDN idle disconnects, with
  `has_oversized_frame()` zero-buffer passthrough (`>16 MiB`, `MemoryMax=128M`),
  `TCP_NODELAY`, and bounded connect timeouts.
- **End-to-end Anycast edge IP selection (`scripts/pick-cf-ip.py`)**:
  Screens unreachable ranges via TCP handshakes and ranks survivors by
  cross-polled end-to-end HTTPS TTFB across `/16` prefixes, supporting
  `--interface` (`IP_BOUND_IF` / `SO_BINDTODEVICE`) to bypass local TUN interfaces.

### Added — Tri-Ecosystem Adaptive Subscription & Dual-Node Routing

- **Zero-dependency Python 3.10+ subscription servers (`subscription/leaf_server.py`, `subscription/aggregator_server.py`, `subscription/_common.py`)**:
  - Single `/<TOKEN>/` endpoint negotiates `profile.json` (`sing-box`),
    `profile.yaml` (`Clash/mihomo` with anti-leak `dns:`, `respect-rules: true`,
    and `packet-encoding: xudp`), or Base64 `profile.txt` (URI bundle for
    Shadowrocket / v2rayN / v2rayNG / Streisand / V2Box / Loon / Quantumult X)
    via User-Agent or `?format=singbox|clash|uris`.
  - Supports `?allow_webrtc=1` per-request override, cached `Accept-Encoding: gzip`
    compression, `Subscription-Userinfo` traffic cards (`BILLING_CYCLE_DAY`,
    `COUNT_CURRENT_BOOT_ON_INIT`, background NIC counter polling), `/<TOKEN>/status`,
    loopback-restricted `/healthz`, optional TLS 1.2+ (`--sub-tls-cert` /
    `--sub-tls-key`), and `Cache-Control: no-store` / `X-Robots-Tag: noindex`.
  - Dual-node aggregator mode (`--with-aggregator`, `--secondary-host`) polls the
    residential leaf `/status`, caches usage across transient outages, and builds
    a unified dual-node profile routing AI/streaming QA via residential egress and
    Telegram/Discord via the data-center node.
- **Unified profile compiler & structural invariant gate (`scripts/build_profile.py`, `scripts/check_profile.py`, `scripts/rebuild-profiles.sh`)**:
  - Compiles all three profile formats from a single params file and enforces
    structural invariants: 100% `type: inline` rule-sets (zero client boot-time
    network fetches, refreshed weekly on the server via `refresh-rulesets.timer`),
    cold-start `⚡ Auto` group ordering, `interrupt_exist_connections: false`,
    `action: resolve` emitted strictly before IP/CIDR rules, and `prefer_ipv4` DNS
    exemption for AAAA-only `challenges.cloudflare.com`.
  - Ships four-layer client routing (LAN direct → ad block → default WebRTC STUN
    leak block on `3478/5349/19302-19309` → priority overseas rules → regional
    split-tunneling via `REGIONAL_SAFETY_NET`, `data/geosite-cn-extra.json`, and
    `geosite/geoip` → default `udp:443` QUIC fallback → proxy).

### Added — Selective Cloudflare WARP Egress & Watchdog

- **Server-side selective WARP WireGuard egress (`--with-warp`, `scripts/warp_egress.py`, `anyreality-resi-stack-warp`)**:
  - Configures native `sing-box` WireGuard endpoint (`02_warp_endpoints.json`),
    `challenges.cloudflare.com` AAAA DNS handling (`05_dns.json`), and a strict
    10-stage C9 route table (`03_route.json`) audited by `warp_egress.py audit`.
  - Includes pre- and post-resolve private-IP SSRF guards, dual-stack IPv6 and
    TCP `CF_CIDRS` preservation, and `EXCLUDE_DIRECT` protection keeping Google,
    Netflix, Disney+, TikTok, and banking on 100% native residential egress while
    routing Turnstile/403-challenged AI/social domains through `warp-ep`.
  - Paired with `warp-watchdog.{service,timer}` probing `127.0.0.1:10809` every
    2 minutes, auto-degrading to `direct` after 3 failures and auto-recovering
    after 3 successes.

### Added — Security Hardening, Operations, Docs & CI

- **Supply-chain, firewall, and service sandboxing**:
  - Pinned Sagernet apt GPG fingerprint (`2C317FBD5D886B4E89BAE8DA6D9152172A2B2F0C`)
    plus `apt-mark hold sing-box` to prevent unattended upgrades from breaking configs.
  - Unprivileged `anyreality-sub` service user (`CAP_NET_BIND_SERVICE` only,
    systemd `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `0600` `secrets.env`).
  - UFW auto-detecting active SSH ports plus pinned Cloudflare IPv4/IPv6 origin
    CIDR allowlists; `nginx` default `ssl_reject_handshake on` SNI stealth;
    `fail2ban`; optional `--harden-ssh`; single consolidated `/etc/sysctl.d/99-anyreality.conf`
    (BBR + `fq` + UDP/QUIC buffers + GRO/GSO offload, verified via `scripts/check_sysctl.py`).
  - Logrotate for `/etc/sing-box/logs/box.log`, verified daily config backups with
    off-box hook support (`/etc/anyreality-resi-stack/backup-hooks.d/`),
    `scripts/healthcheck.sh` (including C3 drift and C9 WARP audits), and
    `scripts/rotate-sub-token.sh` with automatic rollback.
- **Compliance, documentation, and verification gates**:
  - Comprehensive legal compliance and acceptable-use framework in [`DISCLAIMER.md`](DISCLAIMER.md)
    and [`SECURITY.md`](SECURITY.md).
  - Bilingual documentation in `docs/zh-CN/` and `docs/en/` (including
    `MULTIPATH-TRANSPORT.md`, `WARP-EGRESS.md`, `DEPLOYMENT.md`, `DUAL-NODE.md`,
    `SUBSCRIPTION.md`, `ROUTING.md`, `OPERATIONS.md`, `TROUBLESHOOTING.md`,
    `CLIENTS.md`, `COMPARISON.md`, `BEGINNER_GUIDE.md`, `EXAMPLES.md`, `FAQ.md`),
    plus `llms.txt` and `codemeta.json`.
  - GitHub Actions CI (`lint.yml`, `redact.yml`) running `shellcheck`, `shfmt`,
    `ruff`, `yamllint`, `jsonlint`, `markdown-link-check`, `scripts/redact.sh`
    (filename blocklist, UUID/43-char base64url shape detection, and optional
    high-entropy hash denylist), `scripts/make-example.sh`, and 126 standard-library
    unit tests (`tests/`).
