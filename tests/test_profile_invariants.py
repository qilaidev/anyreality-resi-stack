"""The client-profile invariants, and proof that the checker actually catches
their violations.

Every case here corresponds to a failure that `sing-box check` accepted, that
started cleanly, and that produced no server-side symptom at all — while some
subset of users had a client that would not boot, or one that said "connected"
while nothing loaded. A checker nobody has seen fail is not evidence of
anything, so each invariant is asserted twice: the shipped profiles satisfy it,
and a deliberately broken copy is rejected.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE = REPO_ROOT / "examples" / "single-node" / "sing-box-client-config.json"
DUAL = REPO_ROOT / "examples" / "dual-node" / "sing-box-client-dual.json"
CLASH_SINGLE = REPO_ROOT / "examples" / "single-node" / "clash-profile.yaml"
URIS_SINGLE = REPO_ROOT / "examples" / "single-node" / "uris-profile.txt"
URIS_DUAL = REPO_ROOT / "examples" / "dual-node" / "uris-profile.txt"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load("check_profile_under_test", "check_profile.py")
builder = _load("build_profile_under_test", "build_profile.py")


def profile(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class ShippedProfilesTest(unittest.TestCase):
    def test_examples_pass_every_invariant(self) -> None:
        for path in (SINGLE, DUAL):
            with self.subTest(profile=path.name):
                self.assertEqual(checker.check_singbox(profile(path)), [])

    def test_no_remote_rule_sets_anywhere(self) -> None:
        """A remote rule-set is downloaded before startup finishes and a failure
        is fatal, so the client dies at boot on exactly the flaky lines that
        need it most. The download also goes through a proxy group that has not
        converged yet, which is how a dead first member turns into a boot loop.
        """
        for path in (SINGLE, DUAL):
            with self.subTest(profile=path.name):
                for entry in profile(path)["route"]["rule_set"]:
                    self.assertEqual(entry["type"], "inline", entry.get("tag"))

    def test_auto_group_starts_with_the_cdn_path(self) -> None:
        """urltest has no measurements on the first connection and falls back to
        its first member, so slot 0 decides whether the client works at all in
        the seconds after launch."""
        for path in (SINGLE, DUAL):
            with self.subTest(profile=path.name):
                cfg = profile(path)
                by_tag = {o["tag"]: o for o in cfg["outbounds"]}
                auto = by_tag[builder.G_AUTO]
                first = by_tag[auto["outbounds"][0]]
                members = [by_tag[t] for t in first["outbounds"]]
                self.assertTrue(
                    all((m.get("transport") or {}).get("type") == "ws" for m in members),
                    f"{path.name}: auto group starts with {first['tag']}, not the CDN path",
                )

    def test_no_connect_timeout(self) -> None:
        """Measured handshakes from China run 1.3–6.5 s; a 4–8 s cap kills
        connections that would have succeeded."""
        for path in (SINGLE, DUAL):
            for node in profile(path)["outbounds"]:
                self.assertNotIn("connect_timeout", node, node.get("tag"))

    def test_vision_never_multiplexed_and_ws_uses_h2mux(self) -> None:
        for path in (SINGLE, DUAL):
            for node in profile(path)["outbounds"]:
                if node.get("flow") == "xtls-rprx-vision":
                    self.assertNotIn("multiplex", node, node["tag"])
                if (node.get("transport") or {}).get("type") == "ws":
                    self.assertEqual(node["multiplex"]["protocol"], "h2mux", node["tag"])

    def test_probes_never_interrupt_live_connections(self) -> None:
        for path in (SINGLE, DUAL):
            for node in profile(path)["outbounds"]:
                if node.get("type") == "urltest":
                    self.assertFalse(node.get("interrupt_exist_connections"), node["tag"])

    def test_clash_and_singbox_describe_the_same_nodes(self) -> None:
        """Drift guard. Two profiles for one topology have already disagreed
        once — the sing-box side was fine and mihomo refused to load at all, so
        only Clash users saw it."""
        singbox_nodes = {
            o["tag"]
            for o in profile(SINGLE)["outbounds"]
            if o["type"] in ("vless", "hysteria2", "anytls")
        }
        text = CLASH_SINGLE.read_text(encoding="utf-8")
        for tag in singbox_nodes:
            self.assertIn(f"name: {tag}", text, f"{tag} missing from the Clash profile")

    def test_uris_and_singbox_describe_the_same_nodes(self) -> None:
        """URI-native clients (Shadowrocket, v2rayN, v2rayNG, Streisand) must
        receive every node present in the sing-box profile, with no insecure=1."""
        for sb_path, uri_path in ((SINGLE, URIS_SINGLE), (DUAL, URIS_DUAL)):
            with self.subTest(profile=uri_path.name):
                singbox_nodes = {
                    o["tag"]
                    for o in profile(sb_path)["outbounds"]
                    if o["type"] in ("vless", "hysteria2", "anytls")
                }
                problems = checker.check_uris_text(
                    uri_path.read_text(encoding="utf-8"),
                    expected_tags=singbox_nodes,
                )
                self.assertEqual(problems, [])


class CheckerCatchesViolationsTest(unittest.TestCase):
    """Break one thing at a time and require a complaint about that thing."""

    def setUp(self) -> None:
        self.cfg = profile(SINGLE)

    def assert_flags(self, needle: str) -> None:
        problems = checker.check_singbox(self.cfg)
        self.assertTrue(
            any(needle in p for p in problems),
            f"expected a problem mentioning {needle!r}, got: {problems}",
        )

    def test_catches_remote_rule_set(self) -> None:
        self.cfg["route"]["rule_set"][0] = {
            "type": "remote",
            "tag": "geosite-cn",
            "format": "binary",
            "url": "https://example.invalid/geosite-cn.srs",
            "download_detour": builder.G_SELECT,
        }
        self.assert_flags("non-inline")

    def test_catches_reordered_auto_group(self) -> None:
        by_tag = {o["tag"]: o for o in self.cfg["outbounds"]}
        by_tag[builder.G_AUTO]["outbounds"].reverse()
        self.assert_flags("cold start")

    def test_catches_connect_timeout(self) -> None:
        for node in self.cfg["outbounds"]:
            if node.get("type") == "vless":
                node["connect_timeout"] = "4s"
                break
        self.assert_flags("connect_timeout")

    def test_catches_ws_without_h2mux(self) -> None:
        for node in self.cfg["outbounds"]:
            if (node.get("transport") or {}).get("type") == "ws":
                node["multiplex"]["protocol"] = "yamux"
                break
        self.assert_flags("h2mux")

    def test_catches_interrupting_urltest(self) -> None:
        for node in self.cfg["outbounds"]:
            if node.get("type") == "urltest":
                node["interrupt_exist_connections"] = True
                break
        self.assert_flags("interrupt_exist_connections")

    def test_catches_ip_rule_before_resolve(self) -> None:
        rules = self.cfg["route"]["rules"]
        resolve_at = next(i for i, r in enumerate(rules) if r.get("action") == "resolve")
        rules.insert(resolve_at, {"rule_set": "geoip-cn", "outbound": "direct"})
        self.assert_flags("action: resolve")

    def test_catches_insecure_hysteria2(self) -> None:
        for node in self.cfg["outbounds"]:
            if node.get("type") == "hysteria2":
                node["tls"]["insecure"] = True
                break
        self.assert_flags("tls.insecure")

    def test_catches_unparseable_pinned_certificate(self) -> None:
        """sing-box panics on this rather than reporting a config error, so the
        stack trace reads as 'sing-box is broken' instead of 'your certificate
        is malformed'. Verified against sing-box 1.13.14."""
        for node in self.cfg["outbounds"]:
            if node.get("type") == "hysteria2":
                node["tls"]["certificate"] = ["not-a-certificate"]
                break
        self.assert_flags("panics")

    def test_catches_dangling_group_member(self) -> None:
        by_tag = {o["tag"]: o for o in self.cfg["outbounds"]}
        by_tag[builder.G_SELECT]["outbounds"].append("🚀 renamed-and-not-updated")
        self.assert_flags("missing outbound")

    def test_catches_selector_default_pinned_to_one_node(self) -> None:
        """Defaulting to a concrete node removes automatic failover entirely:
        that node dies and the user is simply stuck, with no probe to move
        them."""
        by_tag = {o["tag"]: o for o in self.cfg["outbounds"]}
        node = next(o["tag"] for o in self.cfg["outbounds"] if o.get("type") == "vless")
        by_tag[builder.G_SELECT]["default"] = node
        self.assert_flags("is not a group")

    def test_catches_missing_cf_challenge_dns_exemption(self) -> None:
        self.cfg["dns"]["rules"] = [
            r
            for r in self.cfg["dns"]["rules"]
            if "challenges.cloudflare.com" not in str(r.get("domain_suffix", ""))
        ]
        self.assert_flags("AAAA-only")


class ClashCheckerTest(unittest.TestCase):
    def test_shipped_clash_profile_is_clean(self) -> None:
        self.assertEqual(checker.check_clash_text(CLASH_SINGLE.read_text(encoding="utf-8")), [])

    def test_catches_fallback_group(self) -> None:
        text = CLASH_SINGLE.read_text(encoding="utf-8").replace(
            "type: url-test", "type: fallback", 1
        )
        problems = checker.check_clash_text(text)
        self.assertTrue(any("fallback" in p for p in problems), problems)

    def test_catches_dangling_rule_target(self) -> None:
        text = CLASH_SINGLE.read_text(encoding="utf-8").replace(
            f"MATCH,{builder.G_SELECT}", "MATCH,🎯 Renamed", 1
        )
        problems = checker.check_clash_text(text)
        self.assertTrue(any("Renamed" in p for p in problems), problems)

    def test_uris_checker_catches_insecure_and_missing_tags(self) -> None:
        import base64

        bad_b64 = base64.b64encode(
            b"hysteria2://pass@203.0.113.10:443?sni=example.org&insecure=1#node1\n"
        ).decode("ascii")
        problems = checker.check_uris_text(bad_b64, expected_tags={"node1", "node2"})
        self.assertTrue(any("insecure" in p for p in problems), problems)
        self.assertTrue(any("node2" in p for p in problems), problems)


class DegradedTopologyTest(unittest.TestCase):
    """With fewer paths available the profile must still be valid and sensible."""

    base = {
        "node_name": "T",
        "server": "203.0.113.10",
        "sni": "example.org",
        "protocol": "vless-reality",
        "uuid": "00000000-0000-0000-0000-000000000000",
        "reality_public_key": "B" * 43,
        "short_id": "",
        "port": 443,
    }

    def build(self, **overrides) -> dict:
        params = {**self.base, **overrides}
        return builder.build_singbox(params, builder.load_inline_rulesets(None))

    def test_reality_only_profile_is_valid(self) -> None:
        cfg = self.build()
        self.assertEqual(checker.check_singbox(cfg), [])
        by_tag = {o["tag"]: o for o in cfg["outbounds"]}
        # With nothing else available REALITY has to be in the auto group; the
        # rule that keeps it out elsewhere exists to avoid probing a stalling
        # path, not because the path is unusable.
        self.assertEqual(by_tag[builder.G_AUTO]["outbounds"], [builder.G_REALITY])

    def test_hysteria2_without_cdn_leads_the_auto_group(self) -> None:
        cfg = self.build(
            hysteria2={"enabled": True, "password": "x", "obfs_password": "y"}
        )
        self.assertEqual(checker.check_singbox(cfg), [])
        by_tag = {o["tag"]: o for o in cfg["outbounds"]}
        self.assertEqual(by_tag[builder.G_AUTO]["outbounds"], [builder.G_HY2])

    def test_anytls_cannot_produce_a_clash_profile(self) -> None:
        """mihomo's anytls block has no reality-opts, so the node cannot be
        written down at all. Failing loudly here is the whole point: the silent
        version of this cost a month of Clash users having no working node
        while every server-side check stayed green."""
        params = {**self.base, "protocol": "anytls-reality", "anytls_password": "p"}
        with self.assertRaises(SystemExit):
            builder.build_clash(params, builder.load_inline_rulesets(None))


if __name__ == "__main__":
    unittest.main()
