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
            with self.subTest(target=target):
                cfg = warp.build_warp_route_config(target=target)
                self.assertEqual(warp.audit_route_config(cfg), [])

    def test_catches_challenge_after_ipv6_reject(self) -> None:
        cfg = warp.build_warp_route_config(target="warp-ep")
        rules = cfg["route"]["rules"]
        # Swap rule 2 (challenges.cloudflare.com) and rule 3 (ip_version=6 reject)
        rules[2], rules[3] = rules[3], rules[2]
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
        # Swap resolve and CF_CIDRS
        rules[-2], rules[-1] = rules[-1], rules[-2]
        problems = warp.audit_route_config(cfg)
        self.assertTrue(any("action: resolve" in p for p in problems), problems)


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
                warp.disable_warp(conf_dir, no_reload=True)
                self.assertFalse((conf_dir / "02_warp_endpoints.json").exists())
            finally:
                warp.shutil.which = orig_which


if __name__ == "__main__":
    unittest.main()
