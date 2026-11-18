"""Static & sandboxed operational hygiene tests for templates and installer guards."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class OriginStealthAndServerRouteTest(unittest.TestCase):
    def test_nginx_origin_template_rejects_unknown_sni_and_scrubs_domain_title(self) -> None:
        tmpl = (REPO_ROOT / "templates" / "nginx" / "cdn-origin.conf.tmpl").read_text(
            encoding="utf-8"
        )
        self.assertIn("default_server;", tmpl)
        self.assertIn("ssl_reject_handshake on;", tmpl)
        self.assertIn("server_tokens off;", tmpl)
        self.assertNotIn("<title>@@CDN_DOMAIN@@</title>", tmpl)

    def test_baseline_server_route_blocks_private_ip_ssrf(self) -> None:
        route = json.loads(
            (REPO_ROOT / "templates" / "singbox" / "03_route.json").read_text(
                encoding="utf-8"
            )
        )
        rules = route["route"]["rules"]
        self.assertIn({"ip_is_private": True, "action": "reject"}, rules)


class InstallerSafetyGuardsTest(unittest.TestCase):
    def test_has_valid_ssh_pubkey_rejects_empty_or_garbage_and_accepts_real_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            empty_ak = tmp_dir / "empty"
            empty_ak.write_text("# comment only\n\n", encoding="utf-8")
            bad_ak = tmp_dir / "bad"
            bad_ak.write_text("not-an-ssh-key AAAAB3Nza\n", encoding="utf-8")
            good_ak = tmp_dir / "good"
            good_ak.write_text(
                f"ssh-ed25519 {'A' * 68} test@host\n",
                encoding="utf-8",
            )

            script = (
                f'COMMON_SH_LOADED=1; REPO_ROOT="{REPO_ROOT}"; '
                f'. "{REPO_ROOT}/install/lib/common.sh"; '
                f'. "{REPO_ROOT}/install/lib/system.sh"; '
                "has_valid_ssh_pubkey"
            )

            for bad_path in (str(tmp_dir / "missing"), str(empty_ak), str(bad_ak)):
                res = subprocess.run(
                    ["bash", "-c", script],
                    env={"PATH": "/usr/bin:/bin", "SSH_AUTHORIZED_KEYS_CHECK_PATHS": bad_path},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(res.returncode, 0, f"unexpectedly accepted {bad_path}")

            ok_res = subprocess.run(
                ["bash", "-c", script],
                env={
                    "PATH": "/usr/bin:/bin",
                    "SSH_AUTHORIZED_KEYS_CHECK_PATHS": f"{empty_ak}:{good_ak}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok_res.returncode, 0, ok_res.stderr)

    def test_backup_script_archives_all_managed_units_and_nginx_vhost(self) -> None:
        backup_sh = (REPO_ROOT / "install" / "lib" / "backup.sh").read_text(
            encoding="utf-8"
        )
        for expected in (
            "etc/systemd/system/ws-ping-inject.service",
            "etc/systemd/system/altport-redirect.service",
            "etc/systemd/system/refresh-rulesets.timer",
            "etc/systemd/system/warp-watchdog.timer",
            "etc/systemd/system/anyreality-resi-stack-backup.timer",
            "etc/nginx/sites-available/anyreality-cdn-origin.conf",
            "etc/logrotate.d/sing-box",
        ):
            self.assertIn(expected, backup_sh)

    def test_remote_piped_dry_run_uses_ephemeral_clone_and_singbox_apt_hold_is_present(
        self,
    ) -> None:
        install_sh = (REPO_ROOT / "install" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("BOOTSTRAP_EPHEMERAL", install_sh)
        self.assertIn("--dry-run | -h | --help", install_sh)

        singbox_sh = (REPO_ROOT / "install" / "lib" / "singbox.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("apt-mark hold sing-box", singbox_sh)
        self.assertIn("Suites: *", singbox_sh)


if __name__ == "__main__":
    unittest.main()
