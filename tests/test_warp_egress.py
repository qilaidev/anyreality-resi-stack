"""Unit tests for server-side selective Cloudflare WARP egress and watchdog."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_warp():
    spec = importlib.util.spec_from_file_location(
        "warp_egress_under_test", REPO_ROOT / "scripts" / "warp_egress.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


warp = _load_warp()


class WarpRouteInvariantsTest(unittest.TestCase):
    def test_generated_route_configs_pass_c9_audit(self) -> None:
        for target in ("warp-ep", "direct"):
            for ipv6_available in (False, True):
                with self.subTest(target=target, ipv6_available=ipv6_available):
                    cfg = warp.build_warp_route_config(
                        target=target, ipv6_available=ipv6_available
                    )
                    self.assertEqual(
                        warp.audit_route_config(
                            cfg, require_ipv6_reject=not ipv6_available
                        ),
                        [],
                    )

    def test_catches_challenge_after_ipv6_reject(self) -> None:
        cfg = warp.build_warp_route_config(target="warp-ep", ipv6_available=False)
        rules = cfg["route"]["rules"]
        idx_chal = next(
            i
            for i, r in enumerate(rules)
            if "challenges.cloudflare.com" in (r.get("domain_suffix") or [])
        )
        idx_v6 = next(
            i
            for i, r in enumerate(rules)
            if r.get("ip_version") == 6 and r.get("action") == "reject"
        )
        rules[idx_chal], rules[idx_v6] = rules[idx_v6], rules[idx_chal]
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("AAAA-only" in p for p in problems), problems)

    def test_catches_probe_not_pinned_to_warp_ep(self) -> None:
        cfg = warp.build_warp_route_config(target="direct")
        for rule in cfg["route"]["rules"]:
            if "warp-probe-in" in (rule.get("inbound") or []):
                rule["outbound"] = "direct"
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("warp-probe-in" in p for p in problems), problems)

    def test_catches_cf_cidr_before_resolve(self) -> None:
        cfg = warp.build_warp_route_config(target="warp-ep")
        rules = cfg["route"]["rules"]
        idx_res = next(i for i, r in enumerate(rules) if r.get("action") == "resolve")
        idx_cf = next(i for i, r in enumerate(rules) if "ip_cidr" in r)
        rules[idx_res], rules[idx_cf] = rules[idx_cf], rules[idx_res]
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("action: resolve" in p for p in problems), problems)

    def test_hy2_and_vless_ws_shortcut_only_matches_udp(self) -> None:
        cfg = warp.build_warp_route_config(target="warp-ep")
        rules = cfg["route"]["rules"]
        shortcut = next(
            r for r in rules if "hy2-in" in (r.get("inbound") or [])
        )
        self.assertEqual(shortcut.get("network"), "udp")
        del shortcut["network"]
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("network='udp'" in p for p in problems), problems)

    def test_ssrf_private_ip_rejected_pre_and_post_resolve(self) -> None:
        cfg = warp.build_warp_route_config(target="warp-ep")
        rules = cfg["route"]["rules"]
        idx_probe = next(
            i for i, r in enumerate(rules) if "warp-probe-in" in (r.get("inbound") or [])
        )
        idx_res = next(i for i, r in enumerate(rules) if r.get("action") == "resolve")
        priv_rejects = [
            i
            for i, r in enumerate(rules)
            if r.get("ip_is_private") is True and r.get("action") == "reject"
        ]
        self.assertEqual(len(priv_rejects), 2)
        self.assertLess(idx_probe, priv_rejects[0])
        self.assertLess(priv_rejects[0], idx_res)
        self.assertGreater(priv_rejects[1], idx_res)

        # Turning pre-resolve ip_is_private back into direct must fail C9 audit.
        rules[priv_rejects[0]] = {"ip_is_private": True, "outbound": "direct"}
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("SSRF" in p for p in problems), problems)

    def test_dns_uses_encrypted_tls_and_retains_challenge_rule_on_disable(self) -> None:
        for fn in (warp.build_warp_dns_config, warp.build_baseline_dns_config):
            dns = fn(ipv6_available=False)["dns"]
            self.assertEqual(dns["servers"][0]["type"], "tls")
            self.assertEqual(dns["strategy"], "ipv4_only")
            self.assertTrue(
                any(
                    "challenges.cloudflare.com" in (r.get("domain_suffix") or [])
                    and r.get("strategy") == "prefer_ipv4"
                    for r in dns.get("rules", [])
                )
            )
        self.assertEqual(
            warp.build_warp_dns_config(ipv6_available=True)["dns"]["strategy"],
            "prefer_ipv4",
        )


class WarpWatchdogStateMachineTest(unittest.TestCase):
    def test_enable_degrade_recover_and_disable_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            conf_dir = tmp_dir / "conf"
            conf_dir.mkdir()
            state_file = tmp_dir / "state.json"
            creds_file = tmp_dir / "creds.json"
            creds_file.write_text(
                json.dumps(
                    {
                        "private_key": "A" * 43 + "=",
                        "peer_public_key": "B" * 43 + "=",
                        "interface_v4": "172.16.0.2",
                        "interface_v6": "2606:4700:110::2",
                        "reserved": [1, 2, 3],
                    }
                ),
                encoding="utf-8",
            )

            # Avoid invoking real `sing-box` binary in unit test temp dir
            orig_which = warp.shutil.which
            warp.shutil.which = lambda _cmd: None
            try:
                warp.enable_warp(conf_dir, creds_file, no_reload=True)
                self.assertTrue((conf_dir / "02_warp_endpoints.json").is_file())
                route_cfg = json.loads((conf_dir / "03_route.json").read_text())
                self.assertEqual(warp.current_warp_target(route_cfg), "warp-ep")

                # 2 failures: not yet degraded
                warp.step_watchdog(conf_dir, state_file, probe_ok=False, no_reload=True)
                st = warp.step_watchdog(
                    conf_dir, state_file, probe_ok=False, no_reload=True
                )
                self.assertFalse(st["degraded"])
                self.assertEqual(st["fail_count"], 2)

                # 3rd failure: degrades to direct, while keeping warp-probe-in on warp-ep
                st = warp.step_watchdog(
                    conf_dir, state_file, probe_ok=False, no_reload=True
                )
                self.assertTrue(st["degraded"])
                self.assertEqual(st["last_action"], "degraded")
                route_cfg = json.loads((conf_dir / "03_route.json").read_text())
                self.assertEqual(warp.current_warp_target(route_cfg), "direct")
                self.assertEqual(warp.audit_route_config(route_cfg), [])

                # 3 successes: recovers back to warp-ep
                warp.step_watchdog(conf_dir, state_file, probe_ok=True, no_reload=True)
                warp.step_watchdog(conf_dir, state_file, probe_ok=True, no_reload=True)
                st = warp.step_watchdog(
                    conf_dir, state_file, probe_ok=True, no_reload=True
                )
                self.assertFalse(st["degraded"])
                self.assertEqual(st["last_action"], "recovered")
                route_cfg = json.loads((conf_dir / "03_route.json").read_text())
                self.assertEqual(warp.current_warp_target(route_cfg), "warp-ep")

                # Disable cleans up 02_warp_endpoints.json and restores baseline
                warp.disable_warp(conf_dir, no_reload=True, ipv6_available=False)
                self.assertFalse((conf_dir / "02_warp_endpoints.json").exists())
                base_route = json.loads((conf_dir / "03_route.json").read_text())
                self.assertTrue(warp.route_has_ipv6_reject(base_route))

                # Dual-stack host: preserves native IPv6 across enable/degrade/disable
                warp.enable_warp(
                    conf_dir, creds_file, no_reload=True, ipv6_available=True
                )
                dual_route = json.loads((conf_dir / "03_route.json").read_text())
                self.assertFalse(warp.route_has_ipv6_reject(dual_route))
                for _ in range(3):
                    warp.step_watchdog(
                        conf_dir, state_file, probe_ok=False, no_reload=True
                    )
                degraded_dual = json.loads((conf_dir / "03_route.json").read_text())
                self.assertFalse(warp.route_has_ipv6_reject(degraded_dual))
                self.assertEqual(
                    warp.audit_route_config(degraded_dual, require_ipv6_reject=False),
                    [],
                )
                warp.disable_warp(conf_dir, no_reload=True, ipv6_available=True)
                disabled_dual = json.loads((conf_dir / "03_route.json").read_text())
                self.assertFalse(warp.route_has_ipv6_reject(disabled_dual))
            finally:
                warp.shutil.which = orig_which


if __name__ == "__main__":
    unittest.main()
