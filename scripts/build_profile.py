#!/usr/bin/env python3
"""Build the client profile (sing-box JSON / Clash YAML) from one params file.

Why this exists as a generator instead of a `.tmpl` per format
==============================================================
A client profile for Chinese networks is not one node — it is three *paths*
that fail in different, non-overlapping ways (see docs/*/CHINA-NETWORK.md):

  * REALITY over TCP     — works on China Telecom/Unicom, actively throttled or
                           blackholed on China Mobile / Broadcast-TV lines.
  * Hysteria2 over UDP   — best on lossy links, whole UDP ranges are dropped on
                           some mobile paths.
  * VLESS+WS behind CDN  — the only path left when the bare server IP is
                           blackholed, at the cost of one extra hop.

The number of nodes therefore depends on how many ports and CDN edge IPs the
operator configured, so a static template cannot express it. Two hand-written
templates (JSON + YAML) for the same topology also drift: this repo has already
been bitten by a Clash profile whose `MATCH` target was renamed on one side
only — valid YAML, valid JSON, and mihomo refused to load it while every
sing-box client was fine.

One generator, three renderers, one validator (`scripts/check_profile.py`).

Hard invariants this file must never break (each cost a real outage)
====================================================================
1. NO remote rule-sets. sing-box downloads every `type: remote` rule-set
   *before* it finishes starting, and a failure is FATAL. On a jittery mobile
   line the download goes through the not-yet-converged proxy group, times out,
   and the client dies at boot — looking to the user like "the app won't open".
   Everything is inlined.
2. The auto group's FIRST member must be the path that works on the widest set
   of lines (CDN relay when configured). At cold start urltest has no
   measurements yet and simply uses the first member.
3. No `connect_timeout` on any node. Measured handshakes from China run
   1.3–6.5 s; a 4–8 s cap kills connections that would have succeeded.
4. REALITY + xtls-rprx-vision must NOT carry multiplex (mutually exclusive),
   and the CDN path must use h2mux — yamux/smux over WS-behind-CDN fails with
   `context canceled` on sing-box clients and drops every ~5 min on mihomo.
5. `interrupt_exist_connections` is false everywhere: latency probes must not
   tear down the tunnel currently carrying traffic.

Usage:
    build_profile.py --params p.json --format singbox --out profile.json
    build_profile.py --params p.json --format clash   --out profile.yaml
    build_profile.py --params p.json --format uris    --out profile.txt
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent

# The curated extra rule-set ships with the repo but the script is also
# installed standalone onto the server, so look in both layouts rather than
# assuming a checkout.
EXTRA_CANDIDATES = (
    SCRIPT_DIR / "data" / "geosite-cn-extra.json",
    SCRIPT_DIR.parent / "data" / "geosite-cn-extra.json",
)

# ── Group tags ───────────────────────────────────────────────────────────
# Emoji prefixes are what every China-facing client UI uses; they also make the
# groups sort visually. Keep them ASCII-safe otherwise so the tags survive
# copy/paste through terminals and QR codes.
G_SELECT = "🎯 Select"
G_AUTO = "⚡ Auto"
G_CF = "☁️ CF Relay"
G_HY2 = "📡 Hysteria2"
G_REALITY = "🚀 REALITY"
G_DC = "🏢 Datacenter"

URLTEST_URL = "https://www.gstatic.com/generate_204"

# Latency probe cadence. 30 s was the old value and it actively hurt: on a
# mobile line a REALITY probe hangs 7–12 s before failing, so probing that
# often keeps a tunnel permanently busy failing. 300 s halves the probe traffic
# versus 120 s with no observable loss of switching quality.
URLTEST_INTERVAL = "5m"
# 80 ms of hysteresis. Without it a group flaps between two edges whose latency
# difference is pure noise on a cross-border link (measured sd up to 1.05 s).
URLTEST_TOLERANCE = 80

# Domestic safety net. Inlined literally — independent of any downloaded
# rule-set — so the common domestic services stay direct even when the
# generated rule-sets could not be refreshed. Suffix matching covers
# subdomains.
CN_SAFETY_NET = [
    "12306.cn", "126.com", "163.com", "36kr.com", "abchina.com", "alicdn.com",
    "alipay.com", "aliyun.com", "aliyuncs.com", "amap.com", "autonavi.com",
    "baidu.com", "baiducontent.com", "bankcomm.com", "bankofchina.com",
    "bdstatic.com", "bilibili.com", "biligame.com", "ccb.com", "com.cn",
    "csdn.net", "ctrip.com", "dianping.com", "didiglobal.com", "dingtalk.com",
    "douban.com", "douyin.com", "edu.cn", "ele.me", "feishu.cn", "gov.cn",
    "huxiu.com", "icbc.com.cn", "iqiyi.com", "ixigua.com", "jd.com",
    "jdpay.com", "kuaishou.com", "larksuite.com", "lianjia.com",
    "mafengwo.cn", "meituan.com", "org.cn", "pinduoduo.com", "qq.com",
    "qunar.com", "sankuai.com", "sina.com.cn", "sinaimg.cn", "taobao.com",
    "tencent.com", "tmall.com", "toutiao.com", "wechat.com", "weibo.com",
    "xiaohongshu.com", "ximalaya.com", "xueqiu.com", "youku.com", "zhihu.com",
    "zhipin.com",
]

CF_CHALLENGE = "challenges.cloudflare.com"

# Domains routed to the datacenter node in dual-node mode. Telegram and Discord
# soft-throttle residential ranges that ever hosted a bot: uploads stall on
# "sending…" while everything else on the same node is fine.
DC_DOMAINS = [
    "telegram.org", "telegram.me", "t.me", "telesco.pe", "tdesktop.com",
    "discord.com", "discord.gg", "discordapp.com", "discordapp.net",
    "discord.media",
]
DC_IP_CIDRS = [
    # Telegram DC ranges — needed because the apps connect to bare IPs.
    "91.108.4.0/22", "91.108.8.0/22", "91.108.12.0/22", "91.108.16.0/22",
    "91.108.20.0/22", "91.108.56.0/22", "149.154.160.0/20", "185.76.151.0/24",
]

RULESET_TAGS = ("geosite-cn", "geoip-cn", "geosite-category-ads-all")


# ── Params ───────────────────────────────────────────────────────────────
def load_params(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        params = json.load(handle)
    for key in ("node_name", "server", "sni", "port"):
        if not params.get(key):
            sys.exit(f"build_profile: params.{key} is required")
    return params


def _paths_enabled(params: dict[str, Any]) -> tuple[bool, bool, bool]:
    hy2 = bool(params.get("hysteria2", {}).get("enabled"))
    cf = bool(params.get("cf_ws", {}).get("enabled")) and bool(
        params.get("cf_ws", {}).get("ips")
    )
    return True, hy2, cf


# ── Rule-set loading ─────────────────────────────────────────────────────
def load_inline_rulesets(rulesets_dir: Path | None) -> list[dict[str, Any]]:
    """Return sing-box `route.rule_set` entries, all `type: inline`.

    Missing files are a warning, never a fallback to `type: remote`: a profile
    that boots with a thinner rule-set is a performance problem, while a
    profile that cannot boot is a total outage.
    """
    out: list[dict[str, Any]] = []
    for tag in RULESET_TAGS:
        rules: list[dict[str, Any]] = []
        if rulesets_dir is not None:
            src = rulesets_dir / f"{tag}.json"
            if src.is_file():
                try:
                    with src.open(encoding="utf-8") as handle:
                        rules = json.load(handle).get("rules", [])
                except (OSError, json.JSONDecodeError) as exc:
                    print(f"build_profile: WARNING {src}: {exc}", file=sys.stderr)
        if not rules:
            # Omit the set entirely rather than emitting an empty one: sing-box
            # rejects a rule-set with no rules, and the caller drops the rules
            # that referenced it so nothing dangles. A thinner rule-set costs
            # performance; a profile that will not load costs everything.
            print(
                f"build_profile: WARNING no source for {tag} — omitting it "
                "(run scripts/fetch-rulesets.sh to populate)",
                file=sys.stderr,
            )
            continue
        out.append({"type": "inline", "tag": tag, "rules": rules})

    for extra in EXTRA_CANDIDATES:
        if extra.is_file():
            with extra.open(encoding="utf-8") as handle:
                rules = json.load(handle).get("rules", [])
            if rules:
                out.append(
                    {"type": "inline", "tag": "geosite-cn-extra", "rules": rules}
                )
            break
    return out


# ── sing-box nodes ───────────────────────────────────────────────────────
def _reality_tls(params: dict[str, Any]) -> dict[str, Any]:
    reality = {"enabled": True, "public_key": params["reality_public_key"]}
    if params.get("short_id"):
        reality["short_id"] = params["short_id"]
    return {
        "enabled": True,
        "server_name": params["sni"],
        "utls": {"enabled": True, "fingerprint": "chrome"},
        "reality": reality,
    }


def reality_nodes(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    """One node per reachable TCP port.

    Alt ports are not extra listeners — the server REDIRECTs them to the main
    port in nat/PREROUTING. They exist because interference is per-port and
    per-carrier: 443 measured 3.8 s on one Unicom line while 8880 and 40443
    measured 1.26 s on the same line in the same minute. Giving the client
    several ports to race is worth far more than picking a "best" one.
    """
    ports = [int(params["port"])] + [int(p) for p in params.get("alt_tcp_ports", [])]
    nodes = []
    for port in dict.fromkeys(ports):
        if params.get("protocol") == "anytls-reality":
            node: dict[str, Any] = {
                "type": "anytls",
                "tag": f"{prefix} {port}",
                "server": params["server"],
                "server_port": port,
                "password": params["anytls_password"],
                "idle_session_check_interval": "30s",
                "idle_session_timeout": "30s",
                "min_idle_session": 5,
                "tls": _reality_tls(params),
            }
        else:
            node = {
                "type": "vless",
                "tag": f"{prefix} {port}",
                "server": params["server"],
                "server_port": port,
                "uuid": params["uuid"],
                "flow": "xtls-rprx-vision",
                # UDP-over-TCP encoding. Plain UDP relay over a vision stream
                # stalls on lossy domestic links; xudp is measurably steadier.
                "packet_encoding": "xudp",
                "tls": _reality_tls(params),
            }
            # No `multiplex` key at all: vision and multiplex are mutually
            # exclusive and sing-box rejects the combination at runtime, not at
            # `check` time.
        nodes.append(node)
    return nodes


def hy2_nodes(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    hy2 = params["hysteria2"]
    ports = [int(hy2.get("port", params["port"]))] + [
        int(p) for p in hy2.get("alt_ports", [])
    ]
    tls: dict[str, Any] = {
        "enabled": True,
        "server_name": hy2.get("sni") or params["sni"],
    }
    # Certificate pinning, never `insecure: true`. The installer mints a
    # self-signed certificate when no real one is supplied and pins it here, so
    # the client trusts exactly that one certificate — as strict as a public CA,
    # against a trust anchor of one, and needing neither a domain nor a "skip
    # verification" switch. With no certificate in the params (you brought a
    # real one), verification falls back to the system trust store.
    #
    # There is deliberately no way to emit `insecure: true` from here: it would
    # hand the node password to anyone who can intercept the path, and
    # check_profile.py rejects it.
    if hy2.get("certificate"):
        tls["certificate"] = hy2["certificate"]
    nodes = []
    for port in dict.fromkeys(ports):
        node: dict[str, Any] = {
            "type": "hysteria2",
            "tag": f"{prefix} {port}",
            "server": params["server"],
            "server_port": port,
            "password": hy2["password"],
            "tls": tls,
        }
        if hy2.get("obfs_password"):
            node["obfs"] = {"type": "salamander", "password": hy2["obfs_password"]}
        nodes.append(node)
    return nodes


def cf_nodes(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    """VLESS+WS reaching the origin through the CDN, one node per edge IP.

    The edge IP is dialled directly and the hostname travels in SNI + the WS
    `Host` header, so this path needs no DNS at connect time — which matters
    because DNS is one of the first things to break on a censored line.
    """
    cf = params["cf_ws"]
    nodes = []
    for ip in cf["ips"]:
        nodes.append(
            {
                "type": "vless",
                "tag": f"{prefix} {ip}",
                "server": ip,
                "server_port": int(cf.get("port", 443)),
                "uuid": cf.get("uuid") or params["uuid"],
                "packet_encoding": "xudp",
                "tls": {
                    "enabled": True,
                    "server_name": cf["domain"],
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                },
                "transport": {
                    "type": "ws",
                    "path": cf.get("path", "/"),
                    "headers": {"Host": cf["domain"]},
                    # The CDN closes an idle proxied WebSocket after ~100 s and
                    # TCP keepalive does not count (it is hop-by-hop and dies at
                    # the edge). The origin injects application-level WS pings
                    # (scripts/ws_ping_inject.py) to keep this alive; the client
                    # side needs no setting, but max_early_data keeps the first
                    # round-trip cheap.
                    "max_early_data": 2048,
                    "early_data_header_name": "Sec-WebSocket-Protocol",
                },
                # h2mux specifically. yamux/smux over this path fail instantly
                # with `context canceled` on sing-box clients. 4 concurrent
                # streams: fewer TCP connections would head-of-line block on a
                # lossy link, more would spread the mux across edges.
                "multiplex": {
                    "enabled": True,
                    "protocol": "h2mux",
                    "max_connections": 4,
                    "padding": False,
                },
            }
        )
    return nodes


def _urltest(tag: str, members: list[str]) -> dict[str, Any]:
    return {
        "type": "urltest",
        "tag": tag,
        "outbounds": members,
        "url": URLTEST_URL,
        "interval": URLTEST_INTERVAL,
        "tolerance": URLTEST_TOLERANCE,
        # False, always. True makes every probe cycle tear down the tunnel in
        # use, which on a CDN path re-splits the mux and stalls for minutes.
        "interrupt_exist_connections": False,
    }


def auto_members(has_cf: bool, has_hy2: bool) -> list[str]:
    """Members of the auto group, in cold-start priority order.

    urltest with no measurements yet uses its first member, so the first slot
    must be the path that works on the widest range of lines. That is the CDN
    relay: it is the only one that survives a blackholed server IP.

    Direct REALITY is deliberately excluded whenever another path exists. Not
    because it is a bad protocol, but because probing it on a line that stalls
    the TLS ClientHello for 7–12 s keeps the group busy failing, and because
    two independent measurement rounds (China Mobile, then China Unicom) put
    it last on *both* TTFB and throughput — vision cannot multiplex, so every
    new connection pays a full TCP+TLS handshake. It stays one click away in
    the selector for lines where the bare IP is the fast path.
    """
    members = []
    if has_cf:
        members.append(G_CF)
    if has_hy2:
        members.append(G_HY2)
    if not members:
        members.append(G_REALITY)
    return members


def build_singbox(params: dict[str, Any], rulesets: list[dict[str, Any]]) -> dict[str, Any]:
    _, has_hy2, has_cf = _paths_enabled(params)
    dc = params.get("dc") or None

    outbounds: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []

    reality = reality_nodes(params, "🚀")
    outbounds += reality
    groups.append(_urltest(G_REALITY, [n["tag"] for n in reality]))

    if has_hy2:
        nodes = hy2_nodes(params, "📡")
        outbounds += nodes
        groups.append(_urltest(G_HY2, [n["tag"] for n in nodes]))
    if has_cf:
        nodes = cf_nodes(params, "☁️")
        outbounds += nodes
        groups.append(_urltest(G_CF, [n["tag"] for n in nodes]))

    auto = _urltest(G_AUTO, auto_members(has_cf, has_hy2))

    select_members = [G_AUTO] + [g["tag"] for g in groups]
    dc_nodes: list[dict[str, Any]] = []
    if dc:
        dc_params = {**dc, "protocol": dc.get("protocol", params.get("protocol"))}
        dc_nodes = reality_nodes(dc_params, "🏢")
        outbounds += dc_nodes
        groups.append(_urltest(G_DC, [n["tag"] for n in dc_nodes]))
        select_members.append(G_DC)
    select_members += [n["tag"] for n in outbounds]

    selector = {
        "type": "selector",
        "tag": G_SELECT,
        "outbounds": select_members,
        "default": G_AUTO,
    }

    have = {rs["tag"] for rs in rulesets}

    dns_rules: list[dict[str, Any]] = [
        # The CDN challenge widget lives on an AAAA-only host. Under a global
        # ipv4_only strategy the lookup returns nothing and every CAPTCHA page
        # spins forever. This has to be fixed on the DNS layer: in TUN mode the
        # app resolves the name before opening a socket, so a route rule never
        # gets a say.
        {
            "domain_suffix": [CF_CHALLENGE],
            "action": "route",
            "server": "dns-remote",
            "strategy": "prefer_ipv4",
        },
    ]
    if "geosite-category-ads-all" in have:
        dns_rules.append({"rule_set": "geosite-category-ads-all", "action": "reject"})
    dns_rules.append({"domain_suffix": CN_SAFETY_NET, "server": "dns-direct"})
    for tag in ("geosite-cn-extra", "geosite-cn"):
        if tag in have:
            dns_rules.append({"rule_set": tag, "server": "dns-direct"})

    route_rules: list[dict[str, Any]] = [
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
        {"ip_is_private": True, "outbound": "direct"},
    ]
    if "geosite-category-ads-all" in have:
        route_rules.append({"rule_set": "geosite-category-ads-all", "action": "reject"})
    route_rules.append({"domain_suffix": CN_SAFETY_NET, "outbound": "direct"})
    for tag in ("geosite-cn-extra", "geosite-cn"):
        if tag in have:
            route_rules.append({"rule_set": tag, "outbound": "direct"})
    route_rules.append({"domain_suffix": [CF_CHALLENGE], "outbound": G_SELECT})
    if dc:
        route_rules.append({"domain_suffix": DC_DOMAINS, "outbound": G_DC})
    # Everything after this point matches on IP, so the name has to be resolved
    # first. Without an explicit resolve action an IP-CIDR rule silently never
    # matches domain traffic — a rule that is present, valid, and dead.
    #
    # Only emitted when something downstream actually matches on IP: `resolve`
    # replaces the destination domain with an address for every remaining
    # connection, so adding it "just in case" changes what the node receives.
    needs_resolve = "geoip-cn" in have or bool(dc)
    if needs_resolve:
        route_rules.append({"action": "resolve", "strategy": "ipv4_only"})
    if dc:
        route_rules.append({"ip_cidr": DC_IP_CIDRS, "outbound": G_DC})
    if "geoip-cn" in have:
        route_rules.append({"rule_set": "geoip-cn", "outbound": "direct"})
    if not params.get("allow_quic"):
        # REALITY and the CDN path are TCP-only. Left alone, browsers keep
        # retrying HTTP/3 and only fall back to TCP after a timeout, which the
        # user experiences as "pages hang for a few seconds before loading".
        # Rejecting udp/443 makes the fallback immediate. Hysteria2 itself is
        # unaffected: this matches client traffic, not the tunnel.
        route_rules.append({"network": "udp", "port": 443, "action": "reject"})

    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {
                    "type": "tls",
                    "tag": "dns-remote",
                    "server": "1.1.1.1",
                    "detour": G_SELECT,
                },
                {"type": "udp", "tag": "dns-direct", "server": "223.5.5.5"},
                {"type": "udp", "tag": "dns-direct-backup", "server": "119.29.29.29"},
            ],
            "rules": dns_rules,
            "final": "dns-remote",
            "strategy": "ipv4_only",
            "independent_cache": True,
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            }
        ],
        "outbounds": [selector, auto] + groups + outbounds + [
            {"type": "direct", "tag": "direct"}
        ],
        "route": {
            "rule_set": rulesets,
            "rules": route_rules,
            "final": G_SELECT,
            "auto_detect_interface": True,
            "default_domain_resolver": "dns-direct",
        },
        "experimental": {"cache_file": {"enabled": True, "store_rdrc": True}},
    }


# ── Clash / mihomo ───────────────────────────────────────────────────────
def _clash_reality_proxies(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    if params.get("protocol") == "anytls-reality":
        # mihomo's `anytls` block has no `reality-opts`: there is nowhere to put
        # public-key/short-id, so the node literally cannot be expressed. This
        # is the whole reason AnyReality is not the default any more — the
        # server looked healthy while every Clash user silently had no node.
        return []
    ports = [int(params["port"])] + [int(p) for p in params.get("alt_tcp_ports", [])]
    out = []
    for port in dict.fromkeys(ports):
        out.append(
            {
                "name": f"{prefix} {port}",
                "type": "vless",
                "server": params["server"],
                "port": port,
                "uuid": params["uuid"],
                "network": "tcp",
                "udp": True,
                "tfo": True,
                "tls": True,
                "flow": "xtls-rprx-vision",
                "packet-encoding": "xudp",
                "servername": params["sni"],
                "client-fingerprint": "chrome",
                "reality-opts": {
                    "public-key": params["reality_public_key"],
                    "short-id": params.get("short_id", ""),
                },
            }
        )
    return out


def _clash_hy2_proxies(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    hy2 = params["hysteria2"]
    ports = [int(hy2.get("port", params["port"]))] + [
        int(p) for p in hy2.get("alt_ports", [])
    ]
    out = []
    for port in dict.fromkeys(ports):
        node: dict[str, Any] = {
            "name": f"{prefix} {port}",
            "type": "hysteria2",
            "server": params["server"],
            "port": port,
            "password": hy2["password"],
            "sni": hy2.get("sni") or params["sni"],
        }
        if hy2.get("obfs_password"):
            node["obfs"] = "salamander"
            node["obfs-password"] = hy2["obfs_password"]
        # mihomo pins by certificate fingerprint rather than by PEM. As above,
        # `skip-cert-verify` is not offered.
        if hy2.get("fingerprint_sha256"):
            node["fingerprint"] = hy2["fingerprint_sha256"]
        out.append(node)
    return out


def _clash_cf_proxies(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    cf = params["cf_ws"]
    out = []
    for ip in cf["ips"]:
        out.append(
            {
                "name": f"{prefix} {ip}",
                "type": "vless",
                "server": ip,
                "port": int(cf.get("port", 443)),
                "uuid": cf.get("uuid") or params["uuid"],
                "network": "ws",
                "udp": True,
                "packet-encoding": "xudp",
                "tls": True,
                "servername": cf["domain"],
                "client-fingerprint": "chrome",
                "ws-opts": {
                    "path": cf.get("path", "/"),
                    "headers": {"Host": cf["domain"]},
                },
                # smux stays off. On this path mihomo drops the mux roughly
                # every five minutes; the origin-side WS ping is what keeps the
                # connection alive through the CDN, and it needs no mux.
                "smux": {"enabled": False},
            }
        )
    return out


def build_clash(params: dict[str, Any], rulesets: list[dict[str, Any]]) -> dict[str, Any]:
    _, has_hy2, has_cf = _paths_enabled(params)
    dc = params.get("dc") or None

    proxies: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []

    reality = _clash_reality_proxies(params, "🚀")
    proxies += reality
    if reality:
        groups.append({"name": G_REALITY, "proxies": [p["name"] for p in reality]})
    if has_hy2:
        nodes = _clash_hy2_proxies(params, "📡")
        proxies += nodes
        groups.append({"name": G_HY2, "proxies": [p["name"] for p in nodes]})
    if has_cf:
        nodes = _clash_cf_proxies(params, "☁️")
        proxies += nodes
        groups.append({"name": G_CF, "proxies": [p["name"] for p in nodes]})

    if not proxies:
        sys.exit(
            "build_profile: the selected protocol cannot be expressed in a Clash "
            "profile (mihomo has no reality-opts for anytls). Reinstall with "
            "--protocol vless-reality, or serve only the sing-box profile."
        )

    dc_group = None
    if dc:
        dc_params = {**dc, "protocol": dc.get("protocol", params.get("protocol"))}
        dc_nodes = _clash_reality_proxies(dc_params, "🏢")
        if dc_nodes:
            proxies += dc_nodes
            dc_group = G_DC
            groups.append({"name": G_DC, "proxies": [p["name"] for p in dc_nodes]})

    wanted = auto_members(has_cf, has_hy2)
    auto = [name for name in wanted if any(g["name"] == name for g in groups)] or [
        g["name"] for g in groups
    ]

    def url_test(name: str, members: list[str]) -> dict[str, Any]:
        return {
            "name": name,
            # url-test, never fallback. `fallback` picks the first member that
            # is merely *alive*, which on these lines means permanently pinning
            # the slowest path (measured 11.12 s vs 1.20 s on the same client).
            "type": "url-test",
            "proxies": members,
            "url": URLTEST_URL,
            "interval": 300,
            "tolerance": URLTEST_TOLERANCE,
            "lazy": False,
        }

    proxy_groups = [
        {
            "name": G_SELECT,
            "type": "select",
            "proxies": [G_AUTO] + [g["name"] for g in groups] + [p["name"] for p in proxies],
        },
        url_test(G_AUTO, auto),
    ] + [url_test(g["name"], g["proxies"]) for g in groups]

    # Inline rule providers: same content as the sing-box inline rule-sets, and
    # like them they involve no network at startup. A `http` provider would
    # reintroduce exactly the boot-time download this whole design removes.
    providers: dict[str, Any] = {}
    for entry in rulesets:
        payload = _clash_payload(entry)
        if payload:
            providers[entry["tag"]] = {
                "type": "inline",
                "behavior": "ipcidr" if entry["tag"].startswith("geoip") else "domain",
                "payload": payload,
            }

    rules: list[str] = [f"DOMAIN-SUFFIX,{CF_CHALLENGE},{G_SELECT}"]
    if "geosite-category-ads-all" in providers:
        rules.append("RULE-SET,geosite-category-ads-all,REJECT")
    rules += [f"DOMAIN-SUFFIX,{d},DIRECT" for d in CN_SAFETY_NET]
    for tag in ("geosite-cn-extra", "geosite-cn"):
        if tag in providers:
            rules.append(f"RULE-SET,{tag},DIRECT")
    if dc_group:
        rules += [f"DOMAIN-SUFFIX,{d},{dc_group}" for d in DC_DOMAINS]
        rules += [f"IP-CIDR,{c},{dc_group},no-resolve" for c in DC_IP_CIDRS]
    if "geoip-cn" in providers:
        rules.append("RULE-SET,geoip-cn,DIRECT")
    rules.append("GEOIP,CN,DIRECT,no-resolve")
    if not params.get("allow_quic"):
        rules.append("AND,((NETWORK,udp),(DST-PORT,443)),REJECT")
    rules.append(f"MATCH,{G_SELECT}")

    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "unified-delay": True,
        # Most residential/DC exits have no public IPv6. Leaving IPv6 on makes
        # the client hand unreachable AAAA targets to the node: happy-eyeballs
        # tries v6 first and the user sees a stall before every page load.
        # Note the client's own IPv6 toggle overrides this — keep it off there.
        "ipv6": False,
        "keep-alive-idle": 10,
        "proxies": proxies,
        "proxy-groups": proxy_groups,
        "rule-providers": providers,
        "rules": rules,
    }


def _clash_payload(entry: dict[str, Any]) -> list[str]:
    """Flatten a sing-box source rule-set into a mihomo inline payload."""
    payload: list[str] = []
    for rule in entry.get("rules", []):
        for domain in rule.get("domain", []) or []:
            payload.append(domain)
        for suffix in rule.get("domain_suffix", []) or []:
            payload.append(suffix if suffix.startswith(".") else f"+.{suffix}")
        for cidr in rule.get("ip_cidr", []) or []:
            payload.append(cidr)
    return payload


# ── Base64 URI bundle (Shadowrocket / v2rayN / v2rayNG / Streisand) ──────
def _uri_reality_nodes(params: dict[str, Any], prefix: str) -> list[str]:
    ports = [int(params["port"])] + [int(p) for p in params.get("alt_tcp_ports", [])]
    sni = quote(str(params["sni"]), safe="")
    pbk = quote(str(params["reality_public_key"]), safe="")
    sid = quote(str(params.get("short_id", "")), safe="")
    out: list[str] = []
    for port in dict.fromkeys(ports):
        tag = quote(f"{prefix} {port}", safe="")
        if params.get("protocol") == "anytls-reality":
            pwd = quote(str(params["anytls_password"]), safe="")
            out.append(
                f"anytls://{pwd}@{params['server']}:{port}"
                f"?security=reality&sni={sni}&fp=chrome&pbk={pbk}&sid={sid}#{tag}"
            )
        else:
            uuid = quote(str(params["uuid"]), safe="")
            out.append(
                f"vless://{uuid}@{params['server']}:{port}"
                f"?encryption=none&flow=xtls-rprx-vision&security=reality"
                f"&sni={sni}&fp=chrome&pbk={pbk}&sid={sid}&type=tcp&headerType=none#{tag}"
            )
    return out


def _uri_hy2_nodes(params: dict[str, Any], prefix: str) -> list[str]:
    hy2 = params["hysteria2"]
    ports = [int(hy2.get("port", params["port"]))] + [
        int(p) for p in hy2.get("alt_ports", [])
    ]
    pwd = quote(str(hy2["password"]), safe="")
    sni = quote(str(hy2.get("sni") or params["sni"]), safe="")
    query_parts = [f"sni={sni}"]
    if hy2.get("obfs_password"):
        query_parts.append("obfs=salamander")
        query_parts.append(f"obfs-password={quote(str(hy2['obfs_password']), safe='')}")
    if hy2.get("fingerprint_sha256"):
        query_parts.append(f"pinSHA256={quote(str(hy2['fingerprint_sha256']), safe='')}")
    query = "&".join(query_parts)
    out: list[str] = []
    for port in dict.fromkeys(ports):
        tag = quote(f"{prefix} {port}", safe="")
        out.append(f"hysteria2://{pwd}@{params['server']}:{port}?{query}#{tag}")
    return out


def _uri_cf_nodes(params: dict[str, Any], prefix: str) -> list[str]:
    cf = params["cf_ws"]
    port = int(cf.get("port", 443))
    uuid = quote(str(cf.get("uuid") or params["uuid"]), safe="")
    domain = quote(str(cf["domain"]), safe="")
    path = quote(str(cf.get("path", "/")), safe="")
    out: list[str] = []
    for ip in cf["ips"]:
        tag = quote(f"{prefix} {ip}", safe="")
        out.append(
            f"vless://{uuid}@{ip}:{port}"
            f"?encryption=none&security=tls&sni={domain}&fp=chrome"
            f"&type=ws&host={domain}&path={path}#{tag}"
        )
    return out


def build_uris(params: dict[str, Any]) -> str:
    """Build a Base64-encoded URI subscription for URI-native clients.

    Ordered in cold-start resilience priority (CDN WS relay -> Hysteria2 ->
    direct REALITY -> Datacenter) so clients that default to the first entry in
    a subscription land on the widest-compatibility path first.
    """
    _, has_hy2, has_cf = _paths_enabled(params)
    dc = params.get("dc") or None
    lines: list[str] = []
    if has_cf:
        lines += _uri_cf_nodes(params, "☁️")
    if has_hy2:
        lines += _uri_hy2_nodes(params, "📡")
    lines += _uri_reality_nodes(params, "🚀")
    if dc:
        dc_params = {**dc, "protocol": dc.get("protocol", params.get("protocol"))}
        lines += _uri_reality_nodes(dc_params, "🏢")
    payload = "\n".join(lines).encode("utf-8")
    return base64.b64encode(payload).decode("ascii") + "\n"


# ── YAML emitter ─────────────────────────────────────────────────────────
# Hand-rolled rather than PyYAML: the servers this runs on install nothing
# beyond python3-stdlib (that is a feature of the subscription design), and
# `yaml.safe_dump` on an existing profile has already destroyed every comment
# in a file once. Emitting from a dict we built ourselves has neither problem.
def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>%@`\"'\n") or text != text.strip():
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if text[0] in "-?," or text.lower() in ("yes", "no", "true", "false", "null", "~"):
        return f'"{text}"'
    return text


def to_yaml(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(to_yaml(value, indent + 1))
            elif isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}: {'{}' if isinstance(value, dict) else '[]'}")
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                body = to_yaml(item, indent + 1).split("\n")
                first = body[0].lstrip()
                lines.append(f"{pad}- {first}")
                lines.extend(body[1:])
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(to_yaml(item, indent + 1))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_yaml_scalar(data)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--params", required=True, type=Path)
    ap.add_argument("--format", required=True, choices=("singbox", "clash", "uris"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--rulesets",
        type=Path,
        default=None,
        help="directory holding <tag>.json sing-box source rule-sets",
    )
    args = ap.parse_args()

    params = load_params(args.params)

    if args.format == "uris":
        text = build_uris(params)
    elif args.format == "singbox":
        rulesets = load_inline_rulesets(args.rulesets)
        text = json.dumps(
            build_singbox(params, rulesets), ensure_ascii=False, indent=2
        ) + "\n"
    else:
        rulesets = load_inline_rulesets(args.rulesets)
        header = (
            "# Generated by scripts/build_profile.py — do not edit in place.\n"
            "# Regenerate after changing nodes, ports or CDN edge IPs; a hand\n"
            "# edit here drifts from the sing-box profile built from the same\n"
            "# params, and only the Clash users see the breakage.\n"
        )
        text = header + to_yaml(build_clash(params, rulesets)) + "\n"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
