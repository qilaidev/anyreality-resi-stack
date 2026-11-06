#!/usr/bin/env python3
"""Server-side selective Cloudflare WARP WireGuard egress for sing-box.

Why server-side selective WARP exists in a residential-IP stack
===============================================================
Even a clean residential or ISP-leased IP eventually hits two real-world walls:

1. **ASN / IP reputation challenges on AI & social platforms**: `claude.ai`,
   `chatgpt.com`, `oaistatic.com`, `x.com`, `reddit.com`, and `medium.com`
   periodically slap Cloudflare Turnstile loops or 403 blocks on specific ISP
   prefixes.
2. **AAAA-only Cloudflare Turnstile widget hosts on IPv4-only VPSes**:
   Sub-hosts under `challenges.cloudflare.com` (such as
   `brunhild.challenges.cloudflare.com`) publish *only* AAAA records. On an
   IPv4-only server with `"ip_version": 6, "action": "reject"`, the challenge
   script never loads and every CAPTCHA page spins forever.

Routing *all* traffic through WARP would throw away the residential IP that
the node exists to provide (Google, Netflix, Disney+, banking, and TikTok
must see the residential ISP exit). This tool configures **selective** WARP
egress in `/etc/sing-box/conf/`:

* `02_warp_endpoints.json` — native sing-box 1.11+ `endpoints: [{type: wireguard,
  tag: warp-ep}]` plus two loopback-only HTTP probe inbounds (`warp-probe-in`
  on `127.0.0.1:10809` pinned to `warp-ep`, and `warp-verify-in` on
  `127.0.0.1:10810` following the main route table).
* `03_route.json` — strict 10-stage routing order:
    1. `action: sniff`
    2. `ip_is_private -> direct`
    3. `domain_suffix: [challenges.cloudflare.com] -> warp-ep` (BEFORE the IPv6
       reject rule, because `warp-ep` carries a dual-stack `/32` + `/128` tunnel)
    4. `ip_version: 6 -> reject`
    5. `inbound: [warp-probe-in] -> warp-ep` (always pinned to `warp-ep` so the
       watchdog can detect recovery even while degraded)
    6. `domain_suffix: EXCLUDE_DIRECT -> direct` (Google/Apple/Microsoft/GitHub
       and Netflix/Disney+/TikTok/banking keep the residential IP even when a
       sub-asset sits behind Cloudflare)
    7. `domain_suffix: WARP_SUFFIX / domain: WARP_EXACT -> warp-ep`
    8. `inbound: [hy2-in, vless-ws-in] -> direct` (high-volume paths skip
       post-resolve CIDR inspection for non-WARP domains)
    9. `action: resolve, strategy: ipv4_only`
   10. `ip_cidr: CF_CIDRS -> warp-ep` (catches any remaining Cloudflare-proxied
       site whose origin would otherwise challenge the VPS IP)
* `05_dns.json` — adds a `challenges.cloudflare.com -> prefer_ipv4` DNS rule so
  AAAA records are returned when no A record exists.

Watchdog auto-degrade & recovery (`warp_egress.py watchdog`)
============================================================
Run every 2 minutes by `warp-watchdog.timer`. Probes
`https://cp.cloudflare.com/generate_204` through `127.0.0.1:10809` (`warp-probe-in`):
* 3 consecutive failures -> rewrites `03_route.json` so WARP rules fail open to
  `direct` (keeping `warp-probe-in -> warp-ep`) and reloads `sing-box`.
* 3 consecutive successes while degraded -> restores `warp-ep` and reloads.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CONF_DIR = Path("/etc/sing-box/conf")
DEFAULT_STATE_FILE = Path("/run/anyreality-warp-watchdog/state.json")
PROBE_URL = "https://cp.cloudflare.com/generate_204"
PROBE_PROXY = "http://127.0.0.1:10809"
CF_IPS_V4_URL = "https://www.cloudflare.com/ips-v4"
CF_REG_URL = "https://api.cloudflareclient.com/v0a2158/reg"

FAIL_THRESHOLD = 3
RECOVER_THRESHOLD = 3

# Domains that must ALWAYS exit through WARP (AI platforms, Turnstile, and
# sites that aggressively challenge non-browser/datacenter/residential ASNs).
WARP_SUFFIX: list[str] = [
    "anthropic.com",
    "claude.ai",
    "claudeusercontent.com",
    "openai.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "sora.com",
    "perplexity.ai",
    "x.com",
    "twitter.com",
    "twimg.com",
    "t.co",
    "reddit.com",
    "redd.it",
    "redditmedia.com",
    "redditstatic.com",
    "medium.com",
    "patreon.com",
    "producthunt.com",
    "Substack.com".lower(),
    "discord.com",
    "discordapp.com",
]

WARP_EXACT: list[str] = [
    "challenges.cloudflare.com",
]

# Domains that must KEEP the residential/native IP even if some of their
# subdomains or CDN edges resolve to Cloudflare CIDRs. Evaluated BEFORE
# `WARP_SUFFIX` and BEFORE `CF_CIDRS`.
EXCLUDE_DIRECT: list[str] = [
    # Search / productivity / cloud infra that trusts residential ISP IPs more
    # than shared Cloudflare WARP exits
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "googlevideo.com",
    "youtube.com",
    "ytimg.com",
    "ggpht.com",
    "apple.com",
    "icloud.com",
    "mzstatic.com",
    "microsoft.com",
    "live.com",
    "office.com",
    "office365.com",
    "bing.com",
    "github.com",
    "githubusercontent.com",
    "githubassets.com",
    "amazonaws.com",
    "cloudfront.net",
    # Streaming & regional residential-IP-sensitive platforms
    "netflix.com",
    "nflxvideo.net",
    "nflximg.net",
    "nflxso.net",
    "disneyplus.com",
    "bamgrid.com",
    "hbo.com",
    "max.com",
    "spotify.com",
    "scdn.co",
    "tiktok.com",
    "tiktokv.com",
    "tiktokcdn.com",
    "musical.ly",
    "bytedance.com",
    "ibytedtos.com",
    "ibyteimg.com",
    "twitch.tv",
    "ttvnw.net",
    # Finance / payment gateways that reject shared VPN/WARP exits
    "paypal.com",
    "paypalobjects.com",
    "stripe.com",
    "stripe.network",
    "wise.com",
    # Speedtest / IP check tools so operators see their real residential IP
    # unless testing a WARP-routed domain
    "fast.com",
    "speedtest.net",
    "ipinfo.io",
]

# Cloudflare's official IPv4 edge ranges (https://www.cloudflare.com/ips-v4).
CF_CIDRS: list[str] = [
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "108.162.192.0/18",
    "131.0.72.0/22",
    "141.101.64.0/18",
    "162.158.0.0/15",
    "172.64.0.0/13",
    "173.245.48.0/20",
    "188.114.96.0/20",
    "190.93.240.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
]


def _atomic_write_json(path: Path, data: dict[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def build_warp_endpoints_config(creds: dict[str, Any]) -> dict[str, Any]:
    """Build `02_warp_endpoints.json` from registered WARP credentials."""
    v4 = creds["interface_v4"]
    v6 = creds["interface_v6"]
    if "/" not in v4:
        v4 = f"{v4}/32"
    if "/" not in v6:
        v6 = f"{v6}/128"

    peer: dict[str, Any] = {
        "address": creds.get("endpoint_host", "engage.cloudflareclient.com"),
        "port": int(creds.get("endpoint_port", 2408)),
        "public_key": creds["peer_public_key"],
        "allowed_ips": ["0.0.0.0/0", "::/0"],
    }
    if creds.get("reserved"):
        peer["reserved"] = list(creds["reserved"])

    return {
        "endpoints": [
            {
                "type": "wireguard",
                "tag": "warp-ep",
                "address": [v4, v6],
                "private_key": creds["private_key"],
                "peers": [peer],
                "mtu": int(creds.get("mtu", 1280)),
            }
        ],
        "inbounds": [
            {
                "type": "http",
                "tag": "warp-probe-in",
                "listen": "127.0.0.1",
                "listen_port": 10809,
            },
            {
                "type": "http",
                "tag": "warp-verify-in",
                "listen": "127.0.0.1",
                "listen_port": 10810,
            },
        ],
    }


def build_warp_route_config(target: str = "warp-ep") -> dict[str, Any]:
    """Build `03_route.json` with the 10-stage selective WARP rule chain.

    `target` is `"warp-ep"` during normal operation and `"direct"` when the
    watchdog has auto-degraded a dead WARP tunnel. Crucially, rule #5
    (`warp-probe-in`) ALWAYS stays pinned to `"warp-ep"` so the watchdog can
    detect when the tunnel recovers.
    """
    if target not in ("warp-ep", "direct"):
        raise ValueError(f"unsupported WARP target: {target!r}")
    return {
        "route": {
            "rules": [
                {"action": "sniff"},
                {"ip_is_private": True, "outbound": "direct"},
                {
                    "domain_suffix": ["challenges.cloudflare.com"],
                    "outbound": target,
                },
                {"ip_version": 6, "action": "reject"},
                {"inbound": ["warp-probe-in"], "outbound": "warp-ep"},
                {"domain_suffix": EXCLUDE_DIRECT, "outbound": "direct"},
                {
                    "domain_suffix": WARP_SUFFIX,
                    "domain": WARP_EXACT,
                    "outbound": target,
                },
                {
                    "inbound": ["hy2-in", "vless-ws-in"],
                    "outbound": "direct",
                },
                {"action": "resolve", "strategy": "ipv4_only"},
                {"ip_cidr": CF_CIDRS, "outbound": target},
            ],
            "final": "direct",
            "auto_detect_interface": True,
            "default_domain_resolver": "dns-local",
        }
    }


def build_baseline_route_config() -> dict[str, Any]:
    """Baseline `03_route.json` when WARP is disabled."""
    return {
        "route": {
            "rules": [
                {"action": "sniff"},
                {"ip_version": 6, "action": "reject"},
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": "direct",
            "auto_detect_interface": True,
            "default_domain_resolver": "dns-local",
        }
    }


def build_warp_dns_config() -> dict[str, Any]:
    """Build `05_dns.json` with the `challenges.cloudflare.com` AAAA exemption."""
    return {
        "dns": {
            "servers": [
                {"type": "udp", "tag": "dns-local", "server": "1.1.1.1"},
                {"type": "udp", "tag": "dns-backup", "server": "8.8.8.8"},
            ],
            "rules": [
                {
                    "domain_suffix": ["challenges.cloudflare.com"],
                    "action": "route",
                    "server": "dns-local",
                    "strategy": "prefer_ipv4",
                }
            ],
            "final": "dns-local",
            "strategy": "ipv4_only",
        }
    }


def build_baseline_dns_config() -> dict[str, Any]:
    """Baseline `05_dns.json` when WARP is disabled."""
    return {
        "dns": {
            "servers": [
                {"type": "udp", "tag": "dns-local", "server": "1.1.1.1"},
                {"type": "udp", "tag": "dns-backup", "server": "8.8.8.8"},
            ],
            "final": "dns-local",
            "strategy": "ipv4_only",
        }
    }


# ── Audit invariants (C9) ────────────────────────────────────────────────
def audit_route_config(cfg: dict[str, Any], check_live_cf_ips: bool = False) -> list[str]:
    """Verify every structural invariant on a WARP-enabled `03_route.json`."""
    err: list[str] = []
    rules = cfg.get("route", {}).get("rules", [])
    if not rules:
        return ["route.rules is empty"]

    # 1. Domain rules must not collide with EXCLUDE_DIRECT.
    overlap = sorted(set(WARP_SUFFIX) & set(EXCLUDE_DIRECT))
    if overlap:
        err.append(f"WARP_SUFFIX and EXCLUDE_DIRECT overlap: {', '.join(overlap)}")

    # Find indices of key rules.
    idx_challenge = next(
        (
            i
            for i, r in enumerate(rules)
            if "challenges.cloudflare.com" in (r.get("domain_suffix") or [])
        ),
        None,
    )
    idx_ipv6_reject = next(
        (
            i
            for i, r in enumerate(rules)
            if r.get("ip_version") == 6 and r.get("action") == "reject"
        ),
        None,
    )
    idx_probe = next(
        (
            i
            for i, r in enumerate(rules)
            if "warp-probe-in" in (r.get("inbound") or [])
        ),
        None,
    )
    idx_exclude = next(
        (
            i
            for i, r in enumerate(rules)
            if r.get("outbound") == "direct" and len(r.get("domain_suffix") or []) >= 5
        ),
        None,
    )
    idx_warp_domains = next(
        (
            i
            for i, r in enumerate(rules)
            if "anthropic.com" in (r.get("domain_suffix") or [])
        ),
        None,
    )
    idx_resolve = next(
        (i for i, r in enumerate(rules) if r.get("action") == "resolve"),
        None,
    )
    idx_cf_cidr = next(
        (i for i, r in enumerate(rules) if "ip_cidr" in r),
        None,
    )

    if idx_challenge is None:
        err.append("missing challenges.cloudflare.com route rule")
    if idx_ipv6_reject is None:
        err.append("missing ip_version=6 reject rule")
    if (
        idx_challenge is not None
        and idx_ipv6_reject is not None
        and idx_challenge > idx_ipv6_reject
    ):
        err.append(
            "challenges.cloudflare.com rule comes AFTER ip_version=6 reject — "
            "AAAA-only Turnstile hosts will be rejected before reaching warp-ep"
        )

    if idx_probe is None:
        err.append("missing warp-probe-in route rule")
    elif rules[idx_probe].get("outbound") != "warp-ep":
        err.append(
            f"warp-probe-in outbound is {rules[idx_probe].get('outbound')!r}, "
            "must remain pinned to 'warp-ep' so the watchdog can detect recovery"
        )

    if idx_exclude is None:
        err.append("missing EXCLUDE_DIRECT route rule")
    if idx_warp_domains is None:
        err.append("missing WARP_SUFFIX domain route rule")
    if (
        idx_exclude is not None
        and idx_warp_domains is not None
        and idx_exclude > idx_warp_domains
    ):
        err.append("EXCLUDE_DIRECT must precede WARP_SUFFIX")

    if idx_cf_cidr is not None:
        if idx_resolve is None or idx_resolve > idx_cf_cidr:
            err.append(
                "CF_CIDRS ip_cidr rule comes before `action: resolve` — "
                "domain traffic is un-resolved at that point so the CIDR rule is dead"
            )
        if idx_exclude is not None and idx_exclude > idx_cf_cidr:
            err.append("EXCLUDE_DIRECT must precede CF_CIDRS")

    if check_live_cf_ips and idx_cf_cidr is not None:
        configured = set(rules[idx_cf_cidr].get("ip_cidr") or [])
        try:
            req = urllib.request.Request(
                CF_IPS_V4_URL, headers={"User-Agent": "anyreality-warp-audit/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                live = {
                    line.strip()
                    for line in resp.read().decode("utf-8").splitlines()
                    if line.strip()
                }
            if live and configured != live:
                missing = sorted(live - configured)
                extra = sorted(configured - live)
                err.append(
                    f"CF_CIDRS drift vs cloudflare.com/ips-v4: missing={missing}, extra={extra}"
                )
        except (urllib.error.URLError, OSError) as exc:
            err.append(f"could not fetch live Cloudflare IPs: {exc}")

    return err


# ── X25519 key generation & Cloudflare WARP registration ─────────────────
def generate_x25519_keypair() -> tuple[str, str]:
    """Generate a WireGuard X25519 (private_key_b64, public_key_b64) pair.

    Tries `wg genkey` first, then `sing-box generate reality-keypair` (converting
    base64url to standard base64), then `openssl genpkey -algorithm X25519`.
    """
    if shutil.which("wg"):
        priv = subprocess.check_output(["wg", "genkey"], text=True).strip()
        pub = subprocess.check_output(
            ["wg", "pubkey"], input=priv + "\n", text=True
        ).strip()
        return priv, pub

    if shutil.which("openssl"):
        # DER-encoded PKCS#8 X25519 private key has the 32-byte raw key at the end;
        # SubjectPublicKeyInfo has the 32-byte raw public key at the end.
        priv_der = subprocess.check_output(
            ["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"]
        )
        pub_der = subprocess.check_output(
            ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=priv_der,
        )
        raw_priv = priv_der[-32:]
        raw_pub = pub_der[-32:]
        return (
            base64.b64encode(raw_priv).decode("ascii"),
            base64.b64encode(raw_pub).decode("ascii"),
        )

    raise RuntimeError("neither `wg` nor `openssl` found to generate an X25519 keypair")


def register_warp_account(timeout: float = 15.0) -> dict[str, Any]:
    """Register a free Cloudflare WARP consumer device and return credentials."""
    priv_key, pub_key = generate_x25519_keypair()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    body = json.dumps(
        {
            "key": pub_key,
            "install_id": "",
            "fcm_token": "",
            "tos": now,
            "model": "PC",
            "serial_number": "",
            "locale": "en_US",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        CF_REG_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
            "User-Agent": "okhttp/3.12.1",
            "CF-Client-Version": "a-6.11-2223",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))

    # Cloudflare returns either a direct object or {"result": ...}
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    cfg = result["config"]
    peer = cfg["peers"][0]
    addrs = cfg["interface"]["addresses"]
    endpoint_host, _, endpoint_port = str(peer["endpoint"]["host"]).rpartition(":")

    client_id_b64 = cfg.get("client_id", "")
    reserved: list[int] = [0, 0, 0]
    if client_id_b64:
        try:
            raw_id = base64.b64decode(client_id_b64)
            if len(raw_id) == 3:
                reserved = [int(b) for b in raw_id]
        except Exception:  # noqa: BLE001
            pass

    return {
        "device_id": result.get("id", ""),
        "private_key": priv_key,
        "public_key": pub_key,
        "peer_public_key": peer["public_key"],
        "endpoint_host": endpoint_host or "engage.cloudflareclient.com",
        "endpoint_port": int(endpoint_port) if endpoint_port.isdigit() else 2408,
        "interface_v4": addrs["v4"],
        "interface_v6": addrs["v6"],
        "reserved": reserved,
        "mtu": 1280,
    }


# ── Service validation & reload ──────────────────────────────────────────
def _validate_and_reload(conf_dir: Path, no_reload: bool) -> None:
    if shutil.which("sing-box"):
        res = subprocess.run(
            ["sing-box", "check", "-C", str(conf_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"sing-box check -C {conf_dir} failed:\n{res.stderr}")
    if not no_reload and shutil.which("systemctl"):
        subprocess.run(["systemctl", "reload-or-restart", "sing-box"], check=True)


def enable_warp(
    conf_dir: Path, creds_path: Path, no_reload: bool = False
) -> None:
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    for req_key in ("private_key", "peer_public_key", "interface_v4", "interface_v6"):
        if not creds.get(req_key):
            raise ValueError(f"{creds_path}: missing required key {req_key!r}")

    ep_path = conf_dir / "02_warp_endpoints.json"
    route_path = conf_dir / "03_route.json"
    dns_path = conf_dir / "05_dns.json"

    prev_route = route_path.read_text(encoding="utf-8") if route_path.is_file() else None
    prev_dns = dns_path.read_text(encoding="utf-8") if dns_path.is_file() else None

    route_cfg = build_warp_route_config(target="warp-ep")
    problems = audit_route_config(route_cfg)
    if problems:
        raise RuntimeError(f"internal route invariant error: {problems}")

    try:
        _atomic_write_json(ep_path, build_warp_endpoints_config(creds), mode=0o640)
        _atomic_write_json(route_path, route_cfg)
        _atomic_write_json(dns_path, build_warp_dns_config())
        _validate_and_reload(conf_dir, no_reload=no_reload)
    except Exception:
        ep_path.unlink(missing_ok=True)
        if prev_route is not None:
            route_path.write_text(prev_route, encoding="utf-8")
        if prev_dns is not None:
            dns_path.write_text(prev_dns, encoding="utf-8")
        raise


def disable_warp(conf_dir: Path, no_reload: bool = False) -> None:
    ep_path = conf_dir / "02_warp_endpoints.json"
    route_path = conf_dir / "03_route.json"
    dns_path = conf_dir / "05_dns.json"

    ep_path.unlink(missing_ok=True)
    _atomic_write_json(route_path, build_baseline_route_config())
    _atomic_write_json(dns_path, build_baseline_dns_config())
    _validate_and_reload(conf_dir, no_reload=no_reload)


# ── Watchdog state machine ───────────────────────────────────────────────
def current_warp_target(route_cfg: dict[str, Any]) -> str:
    """Return `'warp-ep'` or `'direct'` based on the active WARP domain rule."""
    for rule in route_cfg.get("route", {}).get("rules", []):
        if "anthropic.com" in (rule.get("domain_suffix") or []):
            return str(rule.get("outbound", "warp-ep"))
    return "warp-ep"


def probe_warp(proxy_url: str = PROBE_PROXY, timeout: float = 8.0) -> bool:
    """Probe `https://cp.cloudflare.com/generate_204` through `warp-probe-in`."""
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        PROBE_URL, headers={"User-Agent": "anyreality-warp-watchdog/1.0"}
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status in (200, 204)
    except Exception:  # noqa: BLE001
        return False


def step_watchdog(
    conf_dir: Path,
    state_file: Path,
    probe_ok: bool,
    no_reload: bool = False,
) -> dict[str, Any]:
    """Advance the watchdog state machine by one probe observation.

    Separated from `probe_warp()` so tests can deterministically drive state
    transitions without opening real sockets.
    """
    ep_path = conf_dir / "02_warp_endpoints.json"
    route_path = conf_dir / "03_route.json"
    if not ep_path.is_file() or not route_path.is_file():
        return {"status": "skipped", "reason": "warp not enabled"}

    state: dict[str, Any] = {"fail_count": 0, "ok_count": 0, "degraded": False}
    if state_file.is_file():
        try:
            state.update(json.loads(state_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

    route_cfg = json.loads(route_path.read_text(encoding="utf-8"))
    active_target = current_warp_target(route_cfg)
    degraded = active_target == "direct"
    state["degraded"] = degraded

    action = "none"
    if probe_ok:
        state["fail_count"] = 0
        state["ok_count"] = int(state.get("ok_count", 0)) + 1
        if degraded and state["ok_count"] >= RECOVER_THRESHOLD:
            _atomic_write_json(route_path, build_warp_route_config(target="warp-ep"))
            _validate_and_reload(conf_dir, no_reload=no_reload)
            state["degraded"] = False
            state["ok_count"] = 0
            action = "recovered"
    else:
        state["ok_count"] = 0
        state["fail_count"] = int(state.get("fail_count", 0)) + 1
        if not degraded and state["fail_count"] >= FAIL_THRESHOLD:
            _atomic_write_json(route_path, build_warp_route_config(target="direct"))
            _validate_and_reload(conf_dir, no_reload=no_reload)
            state["degraded"] = True
            state["fail_count"] = 0
            action = "degraded"

    state["last_probe_ok"] = probe_ok
    state["last_action"] = action
    _atomic_write_json(state_file, state)
    return state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register", help="register a free Cloudflare WARP keypair")
    p_reg.add_argument(
        "--out",
        type=Path,
        default=Path("/etc/anyreality-resi-stack/warp-credentials.json"),
        help="output path for registered credentials JSON",
    )

    p_en = sub.add_parser("enable", help="enable selective WARP egress in sing-box")
    p_en.add_argument("--credentials", required=True, type=Path)
    p_en.add_argument("--conf-dir", type=Path, default=DEFAULT_CONF_DIR)
    p_en.add_argument("--no-reload", action="store_true")

    p_dis = sub.add_parser("disable", help="disable WARP egress and restore baseline route")
    p_dis.add_argument("--conf-dir", type=Path, default=DEFAULT_CONF_DIR)
    p_dis.add_argument("--no-reload", action="store_true")

    p_wd = sub.add_parser("watchdog", help="probe warp-ep and auto-degrade/recover")
    p_wd.add_argument("--conf-dir", type=Path, default=DEFAULT_CONF_DIR)
    p_wd.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    p_wd.add_argument("--probe-proxy", default=PROBE_PROXY)
    p_wd.add_argument("--no-reload", action="store_true")

    p_aud = sub.add_parser("audit", help="audit 03_route.json WARP rule invariants")
    p_aud.add_argument("--conf-dir", type=Path, default=DEFAULT_CONF_DIR)
    p_aud.add_argument("--live-cf-ips", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "register":
        creds = register_warp_account()
        _atomic_write_json(args.out, creds, mode=0o600)
        print(f"warp_egress: registered WARP device {creds.get('device_id')} -> {args.out}")
        return 0

    if args.cmd == "enable":
        enable_warp(args.conf_dir, args.credentials, no_reload=args.no_reload)
        print(f"warp_egress: enabled selective WARP egress in {args.conf_dir}")
        return 0

    if args.cmd == "disable":
        disable_warp(args.conf_dir, no_reload=args.no_reload)
        print(f"warp_egress: disabled WARP egress in {args.conf_dir}")
        return 0

    if args.cmd == "watchdog":
        ok = probe_warp(proxy_url=args.probe_proxy)
        state = step_watchdog(
            args.conf_dir, args.state_file, probe_ok=ok, no_reload=args.no_reload
        )
        print(json.dumps(state))
        return 0

    if args.cmd == "audit":
        route_path = args.conf_dir / "03_route.json"
        if not route_path.is_file():
            print(f"{route_path}: file not found", file=sys.stderr)
            return 1
        cfg = json.loads(route_path.read_text(encoding="utf-8"))
        problems = audit_route_config(cfg, check_live_cf_ips=args.live_cf_ips)
        for p in problems:
            print(f"C9 violation: {p}")
        return 1 if problems else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
