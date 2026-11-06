#!/usr/bin/env python3
"""Structural invariants for a generated client profile.

`sing-box check` validates syntax and schema. Every failure listed below passed
`sing-box check`, started cleanly, logged nothing — and left some subset of
users with a client that either would not boot or showed "connected" while
nothing loaded. Those are the failures worth a dedicated checker, because the
server side looks perfectly healthy while they happen.

Exit status 0 = all invariants hold. Non-zero = at least one is violated, with
one line per problem on stdout.

    check_profile.py profile.json [profile.yaml] [profile.txt]
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

GROUP_TYPES = ("selector", "urltest")
NODE_TYPES = ("vless", "anytls", "hysteria2", "trojan", "shadowsocks", "tuic")


def _is_reality(node: dict[str, Any]) -> bool:
    return bool((node.get("tls") or {}).get("reality", {}).get("enabled"))


def _is_ws(node: dict[str, Any]) -> bool:
    return (node.get("transport") or {}).get("type") == "ws"


def check_singbox(cfg: dict[str, Any]) -> list[str]:
    err: list[str] = []
    outbounds = cfg.get("outbounds", [])
    by_tag = {o.get("tag"): o for o in outbounds}
    groups = {o["tag"]: o for o in outbounds if o.get("type") in GROUP_TYPES}
    nodes = {o["tag"]: o for o in outbounds if o.get("type") in NODE_TYPES}

    # ── 1. Rule-sets: inline only ─────────────────────────────────────────
    # A remote rule-set is fetched before startup completes and a failure is
    # fatal. When `download_detour` points at a proxy group that has not
    # converged yet, the fetch goes out over whichever member happens to be
    # first, and on a line where that member is dead the client dies at boot,
    # restarts, and dies again. Users report "the app won't open"; nothing on
    # the server shows anything wrong.
    rule_sets = cfg.get("route", {}).get("rule_set", [])
    remote = [rs.get("tag") for rs in rule_sets if rs.get("type") != "inline"]
    if remote:
        err.append(
            "route.rule_set has non-inline entries "
            + ", ".join(map(str, remote))
            + " — these are downloaded during startup and a failure is FATAL"
        )
    declared = {rs.get("tag") for rs in rule_sets}

    # ── 2. Group wiring ───────────────────────────────────────────────────
    for group in groups.values():
        members = group.get("outbounds") or []
        if not members:
            err.append(f"{group['tag']} is an empty group")
        for member in members:
            if member not in by_tag:
                err.append(f"{group['tag']} references missing outbound {member}")
        default = group.get("default")
        if default and default not in by_tag:
            err.append(f"{group['tag']} default={default} does not exist")

    selectors = [g for g in groups.values() if g.get("type") == "selector"]
    if len(selectors) != 1:
        err.append(f"expected exactly one selector group, found {len(selectors)}")
        return err
    selector = selectors[0]
    auto_tag = selector.get("default")

    if auto_tag not in groups:
        err.append(f"selector default={auto_tag} is not a group")
        return err
    auto = groups[auto_tag]
    if auto.get("type") != "urltest":
        err.append(
            f"selector default={auto_tag} is type={auto.get('type')} — only urltest "
            "gives automatic failover; anything else pins the user to one path"
        )

    def leaves(tag: str, seen: set[str] | None = None) -> list[dict[str, Any]]:
        seen = seen or set()
        if tag in seen or tag not in by_tag:
            return []
        seen.add(tag)
        node = by_tag[tag]
        if node.get("type") in GROUP_TYPES:
            out: list[dict[str, Any]] = []
            for member in node.get("outbounds") or []:
                out.extend(leaves(member, seen))
            return out
        return [node]

    # ── 3. The auto group has to survive a cold start ─────────────────────
    # urltest has no measurements on the very first connection and falls back
    # to its first member. Whatever sits in slot 0 therefore decides whether
    # the client works at all in the first seconds after launch — and on a line
    # where the bare server IP is blackholed, only the CDN path answers.
    auto_members = auto.get("outbounds") or []
    all_leaves = [n for tag in by_tag for n in ([by_tag[tag]] if tag in nodes else [])]
    has_cdn = any(_is_ws(n) for n in all_leaves)
    if has_cdn:
        first = auto_members[0] if auto_members else None
        first_leaves = leaves(first) if first else []
        if not first_leaves or not all(_is_ws(n) for n in first_leaves):
            err.append(
                f"{auto_tag} first member is {first!r}, not the CDN relay path — "
                "cold start uses the first member and only the CDN path works on "
                "lines where the server IP is blackholed"
            )

    for member in auto_members:
        member_type = by_tag.get(member, {}).get("type")
        if member_type in NODE_TYPES:
            err.append(
                f"{auto_tag} member {member} is a concrete node, not a path group — "
                "flattening ports into the auto group makes it re-split the mux "
                "between ports on every probe cycle"
            )

    auto_leaves = leaves(auto_tag)
    if not auto_leaves:
        err.append(f"{auto_tag} resolves to no usable node")
    direct_reality = [n for n in auto_leaves if _is_reality(n)]
    if direct_reality and len(auto_members) > 1:
        err.append(
            f"{auto_tag} mixes direct REALITY ({direct_reality[0]['tag']}) with other "
            "paths — probing it on a line that stalls the TLS ClientHello for 7–12 s "
            "keeps the group busy failing; keep it in the selector only"
        )

    sel_leaves = leaves(selector["tag"])
    if not any(_is_reality(n) for n in sel_leaves):
        err.append(
            f"{selector['tag']} has no direct REALITY node — lines where the bare IP "
            "is the fast path lose their manual entry point"
        )

    # ── 4. Per-node settings that break real connections ──────────────────
    for node in nodes.values():
        if node.get("connect_timeout"):
            err.append(
                f"{node['tag']} sets connect_timeout={node['connect_timeout']} — "
                "measured handshakes from China run 1.3–6.5 s and a cap this low "
                "kills connections that would have succeeded"
            )
        if _is_reality(node) and node.get("flow") == "xtls-rprx-vision" and node.get("multiplex"):
            err.append(
                f"{node['tag']} combines xtls-rprx-vision with multiplex — mutually "
                "exclusive, and the failure only shows up on a real connection"
            )
        if node.get("type") == "hysteria2":
            tls = node.get("tls") or {}
            if tls.get("insecure"):
                err.append(
                    f"{node['tag']} sets tls.insecure — the node password then travels to "
                    "whoever can intercept the path. Pin the server certificate with "
                    "tls.certificate instead; a self-signed certificate verified against a "
                    "trust anchor of one is as strict as a public one"
                )
            certificate = tls.get("certificate")
            if certificate is not None:
                pem = (
                    "\n".join(certificate)
                    if isinstance(certificate, list)
                    else str(certificate)
                )
                begin = "-----BEGIN CERTIFICATE-----"
                end = "-----END CERTIFICATE-----"
                if begin not in pem or end not in pem:
                    # Worth its own check because sing-box *panics* on an
                    # unparseable pinned certificate rather than reporting an
                    # error, and a panic reads as "sing-box is broken".
                    err.append(
                        f"{node['tag']} pins tls.certificate but it is not PEM — sing-box "
                        "panics on this rather than reporting a config error"
                    )
        if _is_ws(node):
            protocol = (node.get("multiplex") or {}).get("protocol")
            if protocol != "h2mux":
                err.append(
                    f"{node['tag']} is WS-behind-CDN with mux protocol={protocol!r} — "
                    "must be h2mux; yamux/smux fail immediately with `context canceled`"
                )

    for group in groups.values():
        if group.get("type") == "urltest" and group.get("interrupt_exist_connections"):
            err.append(
                f"{group['tag']} sets interrupt_exist_connections=true — every latency "
                "probe then tears down the tunnel currently carrying traffic"
            )

    referenced = {m for g in groups.values() for m in (g.get("outbounds") or [])}
    for tag in nodes:
        if tag not in referenced:
            err.append(f"node {tag} is not referenced by any group (renamed and missed?)")

    # ── 5. Route rule order ───────────────────────────────────────────────
    rules = cfg.get("route", {}).get("rules", [])
    resolve_at = next(
        (i for i, r in enumerate(rules) if r.get("action") == "resolve"), None
    )
    geoip_at = next(
        (
            i
            for i, r in enumerate(rules)
            if "ip_cidr" in r or str(r.get("rule_set", "")).startswith("geoip")
        ),
        None,
    )
    if geoip_at is not None and (resolve_at is None or resolve_at > geoip_at):
        err.append(
            "an IP-based rule comes before `action: resolve` — in TUN mode the "
            "destination is still a domain at that point, so the rule is present, "
            "valid and permanently dead"
        )

    for rule in rules:
        target = rule.get("outbound")
        if target and target not in by_tag and target != "direct":
            err.append(f"route rule targets missing outbound {target}")
        rs = rule.get("rule_set")
        for tag in [rs] if isinstance(rs, str) else (rs or []):
            if tag not in declared:
                err.append(f"route rule references undeclared rule_set {tag}")

    final = cfg.get("route", {}).get("final")
    if final not in by_tag:
        err.append(f"route.final={final!r} does not exist")

    # ── 6. DNS ────────────────────────────────────────────────────────────
    dns = cfg.get("dns", {})
    dns_rules = dns.get("rules", [])
    challenge = next(
        (
            r
            for r in dns_rules
            if "challenges.cloudflare.com" in str(r.get("domain_suffix", ""))
        ),
        None,
    )
    if dns.get("strategy") == "ipv4_only" and challenge is None:
        err.append(
            "dns.strategy=ipv4_only without a challenges.cloudflare.com exemption — "
            "the challenge widget host is AAAA-only, so CAPTCHA pages spin forever. "
            "The fix must live on the DNS layer: in TUN mode the app resolves the "
            "name before any route rule can act"
        )
    elif challenge is not None and challenge.get("strategy") == "ipv4_only":
        err.append(
            "the challenges.cloudflare.com DNS rule re-applies ipv4_only, which is "
            "the exact condition it exists to escape"
        )
    for rule in dns_rules:
        server = rule.get("server")
        if server and server not in {s.get("tag") for s in dns.get("servers", [])}:
            err.append(f"dns rule references missing server {server}")
        rs = rule.get("rule_set")
        for tag in [rs] if isinstance(rs, str) else (rs or []):
            if tag not in declared:
                err.append(f"dns rule references undeclared rule_set {tag}")

    return err


# ── Clash / mihomo ───────────────────────────────────────────────────────
# Deliberately parsed with a tiny reader rather than PyYAML: the servers that
# run this install nothing outside the Python stdlib. Only the handful of keys
# whose breakage is invisible from the sing-box side are read.
def check_clash_text(text: str) -> list[str]:
    err: list[str] = []
    names = set(re.findall(r"^\s*-\s+name:\s*(.+?)\s*$", text, re.M))
    if not names:
        err.append("clash profile declares no proxies or groups")
        return err
    known = names | {"DIRECT", "REJECT", "PASS", "GLOBAL"}

    # The rule target is the last field, after dropping trailing modifiers.
    # A renamed group that a rule still points at makes mihomo refuse the whole
    # profile, while the sing-box profile built from the same params stays
    # perfectly valid — so only Clash users ever see the breakage.
    modifiers = {"no-resolve", "src"}
    in_rules = False
    for line in text.splitlines():
        if re.match(r"^rules:\s*$", line):
            in_rules = True
            continue
        if in_rules and line and not line.startswith((" ", "-", "\t")):
            in_rules = False
        if not in_rules:
            continue
        item = re.match(r"^\s*-\s+(.*?)\s*$", line)
        if not item:
            continue
        rule = item.group(1).strip("\"'")
        if "(" in rule:  # logical rule: commas nest, target is still last
            rule = rule.rsplit(",", 1)[-1]
            fields = [rule]
        else:
            fields = [f.strip() for f in rule.split(",")]
        while len(fields) > 1 and fields[-1] in modifiers:
            fields.pop()
        target = fields[-1]
        if target and target not in known:
            err.append(f"clash rule targets unknown proxy/group {target!r}")

    if re.search(r"^\s*type:\s*fallback\s*$", text, re.M):
        err.append(
            "clash group uses type: fallback — fallback picks the first member that "
            "is merely alive, which pins the user to the slowest path (11.12 s vs "
            "1.20 s measured on one line). Use url-test"
        )
    if "network: ws" in text and "smux" in text:
        block = text.split("proxy-groups:")[0]
        if re.search(r"smux:\s*\n\s*enabled:\s*true", block):
            err.append(
                "clash WS proxy enables smux — it drops roughly every 5 minutes on this path"
            )
    return err


# ── Base64 URI bundle ────────────────────────────────────────────────────
URI_SCHEMES = ("vless://", "hysteria2://", "anytls://")


def check_uris_text(text: str, expected_tags: set[str] | None = None) -> list[str]:
    err: list[str] = []
    raw = text.strip()
    if not raw:
        return ["uris profile is empty"]
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        return [f"uris profile is not valid base64 UTF-8: {exc}"]

    lines = [line.strip() for line in decoded.splitlines() if line.strip()]
    if not lines:
        return ["uris profile decodes to zero URI lines"]

    seen_tags: set[str] = set()
    for idx, line in enumerate(lines, 1):
        if not line.startswith(URI_SCHEMES):
            err.append(f"line {idx}: unsupported URI scheme in {line[:24]!r}")
        if re.search(r"(?:insecure|allowInsecure)\s*=\s*(?:1|true)", line, re.I):
            err.append(
                f"line {idx}: URI enables insecure TLS verification — use pinSHA256 instead"
            )
        if "#" not in line:
            err.append(f"line {idx}: URI is missing a #fragment node tag")
        else:
            seen_tags.add(unquote(line.split("#", 1)[1]))

    if expected_tags is not None:
        missing = sorted(expected_tags - seen_tags)
        if missing:
            err.append(
                "uris profile is missing node tags present in sing-box profile: "
                + ", ".join(missing)
            )
    return err


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    problems: list[str] = []

    singbox_path = Path(argv[0])
    try:
        with singbox_path.open(encoding="utf-8") as handle:
            cfg = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{singbox_path}: {exc}")
        return 1
    problems += [f"{singbox_path.name}: {p}" for p in check_singbox(cfg)]
    singbox_tags = {
        o["tag"]
        for o in cfg.get("outbounds", [])
        if o.get("type") in NODE_TYPES and o.get("tag")
    }

    for extra_arg in argv[1:]:
        extra_path = Path(extra_arg)
        try:
            text = extra_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"{extra_path}: {exc}")
            return 1
        if extra_path.suffix.lower() in (".txt", ".uris"):
            problems += [
                f"{extra_path.name}: {p}"
                for p in check_uris_text(text, expected_tags=singbox_tags)
            ]
        else:
            problems += [f"{extra_path.name}: {p}" for p in check_clash_text(text)]

    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
