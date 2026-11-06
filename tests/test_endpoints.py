"""End-to-end coverage of the served HTTP surface.

Until now nothing exercised the request path: the routing, the token check, the
usage-card headers, and the traversal guard were all only reachable through a
live server. This boots the real leaf server on an ephemeral port and drives it
over HTTP, so a refactor of the shared handler cannot silently change what
clients receive.
"""

from __future__ import annotations

import gzip
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TOKEN = "endpoint-test-token"
# Padded past the server's compression threshold on purpose: a real profile with
# the routing rule-sets inlined is hundreds of KiB, and a fixture small enough to
# skip compression would make the gzip tests silently vacuous.
PROFILE_BODY = (
    '{"outbounds": [], "_pad": "' + "x" * 4096 + '"}\n'
)


def load_leaf_with_env(env: dict[str, str]):
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            "leaf_endpoints_under_test", REPO_ROOT / "subscription" / "leaf_server.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class LeafEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        file_dir = Path(cls.tmp.name) / "files"
        file_dir.mkdir()
        (file_dir / "profile.json").write_text(PROFILE_BODY, encoding="utf-8")
        # The Clash profile has to exist too: format selection falls back to
        # DEFAULT_TARGET when the file a client family needs is absent, and a
        # test that only ever had one file could not tell the two apart.
        # Padded past the compression threshold so the gzip tests are meaningful.
        (file_dir / "profile.yaml").write_text(
            "proxies: []\n# " + "y" * 4096 + "\n", encoding="utf-8"
        )
        (file_dir / "profile.txt").write_text(
            "dmxlc3M6Ly9leGFtcGxl\n", encoding="utf-8"
        )
        # A file the token holder must never be able to reach via the URL.
        (Path(cls.tmp.name) / "secrets.env").write_text("SECRET=1\n", encoding="utf-8")

        cls.leaf = load_leaf_with_env({
            "TOKEN": TOKEN,
            "FILE_DIR": str(file_dir),
            "DEFAULT_TARGET": "profile.json",
            "STATE_FILE": str(Path(cls.tmp.name) / "usage-state.json"),
            "INTERFACE": "definitely-not-a-nic",
            "PROFILE_TITLE": "Endpoint-Test-Node",
            "TOTAL_BYTES": "1024",
            "EXPIRE_TS": "0",
            "UPDATE_INTERVAL_HOURS": "12",
        })

        cls.server = cls.leaf._common.SubscriptionHTTPServer(
            ("127.0.0.1", 0), cls.leaf.SubscriptionHandler
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def get(self, path: str, method: str = "GET", headers: dict | None = None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers or {}
        )
        return urllib.request.urlopen(request, timeout=5)  # noqa: S310

    # ── format selection ─────────────────────────────────────────────────
    def test_bare_token_picks_the_format_the_client_can_parse(self) -> None:
        """One URL has to serve both ecosystems.

        Handing every client one canonical format means half of them download a
        file they cannot read — and the server sees a 200, so nothing looks
        wrong from this side. The user just gets an empty or broken profile.
        """
        cases = [
            ("sing-box 1.13.0", "profile.json"),
            ("SFA/1.9 (sing-box)", "profile.json"),
            ("Karing/1.0", "profile.json"),
            ("Hiddify/2.0", "profile.json"),
            ("ClashforWindows/0.20.39", "profile.yaml"),
            ("mihomo/1.18.1", "profile.yaml"),
            ("Stash/2.5", "profile.yaml"),
            ("Shadowrocket/2070", "profile.txt"),
            ("v2rayN/6.45", "profile.txt"),
            ("v2rayNG/1.8.19", "profile.txt"),
            ("Streisand/1.6", "profile.txt"),
            # Unrecognised clients, browsers and curl fall back to the
            # configured default rather than guessing.
            ("curl/8.5.0", "profile.json"),
            ("", "profile.json"),
        ]
        for agent, expected in cases:
            with (
                self.subTest(user_agent=agent),
                self.get(f"/{TOKEN}/", headers={"User-Agent": agent}) as response,
            ):
                self.assertIn(expected, response.headers["Content-Disposition"])

    def test_format_query_parameter_overrides_user_agent(self) -> None:
        cases = [
            ("clash", "sing-box 1.13.0", "profile.yaml"),
            ("uris", "sing-box 1.13.0", "profile.txt"),
            ("singbox", "Shadowrocket/2070", "profile.json"),
        ]
        for fmt, agent, expected in cases:
            with (
                self.subTest(format=fmt, user_agent=agent),
                self.get(
                    f"/{TOKEN}/?format={fmt}", headers={"User-Agent": agent}
                ) as response,
            ):
                self.assertIn(expected, response.headers["Content-Disposition"])

    def test_explicit_filename_beats_user_agent_sniffing(self) -> None:
        with self.get(
            f"/{TOKEN}/profile.yaml", headers={"User-Agent": "sing-box 1.13.0"}
        ) as response:
            self.assertIn("profile.yaml", response.headers["Content-Disposition"])

    # ── compression ──────────────────────────────────────────────────────
    def test_gzip_is_served_when_offered(self) -> None:
        """A profile with the rule-sets inlined is hundreds of KiB to megabytes,
        re-downloaded on every subscription refresh over exactly the congested
        links this project targets. Uncompressed, that update is what times out.
        """
        with self.get(
            f"/{TOKEN}/", headers={"Accept-Encoding": "gzip"}
        ) as response:
            self.assertEqual(response.headers["Content-Encoding"], "gzip")
            self.assertEqual(response.headers["Vary"], "Accept-Encoding")
            body = response.read()
            self.assertEqual(int(response.headers["Content-Length"]), len(body))
            self.assertEqual(gzip.decompress(body).decode(), PROFILE_BODY)

    def test_no_gzip_when_not_offered(self) -> None:
        with self.get(f"/{TOKEN}/") as response:
            self.assertIsNone(response.headers.get("Content-Encoding"))
            self.assertEqual(response.read().decode(), PROFILE_BODY)

    def test_gzip_is_declined_at_q_zero(self) -> None:
        with self.get(
            f"/{TOKEN}/", headers={"Accept-Encoding": "gzip;q=0, identity"}
        ) as response:
            self.assertIsNone(response.headers.get("Content-Encoding"))

    def test_head_reports_the_compressed_length(self) -> None:
        """A HEAD advertising the uncompressed length makes clients that
        pre-allocate from it truncate the real download."""
        with self.get(
            f"/{TOKEN}/", method="HEAD", headers={"Accept-Encoding": "gzip"}
        ) as head:
            self.assertEqual(head.headers["Content-Encoding"], "gzip")
            head_length = int(head.headers["Content-Length"])
            self.assertEqual(head.read(), b"")
        with self.get(f"/{TOKEN}/", headers={"Accept-Encoding": "gzip"}) as body:
            self.assertEqual(head_length, len(body.read()))

    def assert_status(self, path: str, expected: int, method: str = "GET") -> None:
        try:
            with self.get(path, method) as response:
                self.assertEqual(response.status, expected)
        except urllib.error.HTTPError as exc:
            with exc:
                self.assertEqual(exc.code, expected)

    # ── liveness ─────────────────────────────────────────────────────────
    def test_healthz_is_unauthenticated_and_json(self) -> None:
        response = self.get("/healthz")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload, {"ok": True, "service": "Endpoint-Test-Node"})

    # ── profile delivery ─────────────────────────────────────────────────
    def test_default_target_is_served_with_usage_card_headers(self) -> None:
        response = self.get(f"/{TOKEN}/")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read().decode("utf-8"), PROFILE_BODY)
        self.assertEqual(response.headers["Profile-Title"], "Endpoint-Test-Node")
        self.assertEqual(response.headers["Profile-Update-Interval"], "12")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("filename=\"profile.json\"", response.headers["Content-Disposition"])
        self.assertRegex(
            response.headers["Subscription-Userinfo"],
            r"^upload=0; download=\d+; total=1024; expire=0$",
        )

    def test_named_target_is_served(self) -> None:
        self.assert_status(f"/{TOKEN}/profile.json", 200)

    def test_head_returns_headers_without_a_body(self) -> None:
        response = self.get(f"/{TOKEN}/", method="HEAD")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b"")
        self.assertEqual(response.headers["Content-Length"], str(len(PROFILE_BODY)))

    def test_status_endpoint_reports_usage(self) -> None:
        response = self.get(f"/{TOKEN}/status")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["total_bytes"], 1024)
        self.assertEqual(payload["profile_title"], "Endpoint-Test-Node")
        self.assertIn("reported_used_bytes", payload)

    # ── access control ───────────────────────────────────────────────────
    def test_wrong_token_is_404(self) -> None:
        self.assert_status("/not-the-token/", 404)

    def test_bare_root_is_404(self) -> None:
        self.assert_status("/", 404)

    def test_encoded_traversal_cannot_escape_file_dir(self) -> None:
        """Percent-encoding survives urllib's path normalisation, so this is the
        shape an attacker with the token would actually send."""
        for escaped in ("%2e%2e%2fsecrets.env", "%2e%2e", "%2e"):
            with self.subTest(target=escaped):
                self.assert_status(f"/{TOKEN}/{escaped}", 404)

    def test_missing_file_is_404(self) -> None:
        self.assert_status(f"/{TOKEN}/nope.yaml", 404)

    def test_query_string_is_ignored(self) -> None:
        self.assert_status(f"/{TOKEN}/?flag=1", 200)


class TLSEndpointTest(unittest.TestCase):
    """The TLS path must actually serve, not just build a context.

    ``wrap_socket`` happens inside ``get_request``, where a mistake shows up as
    dropped connections rather than a startup error — so exercise it for real.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import shutil
        import ssl
        import subprocess

        if not shutil.which("openssl"):
            raise unittest.SkipTest("openssl not available")

        cls.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(cls.tmp.name)
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        result = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", "1",
             "-subj", "/CN=localhost"],
            capture_output=True, check=False,
        )
        if result.returncode != 0:
            cls.tmp.cleanup()
            raise unittest.SkipTest("openssl could not generate a test certificate")

        file_dir = tmp_path / "files"
        file_dir.mkdir()
        (file_dir / "profile.json").write_text(PROFILE_BODY, encoding="utf-8")

        cls.leaf = load_leaf_with_env({
            "TOKEN": TOKEN,
            "FILE_DIR": str(file_dir),
            "DEFAULT_TARGET": "profile.json",
            "STATE_FILE": str(tmp_path / "usage-state.json"),
            "INTERFACE": "definitely-not-a-nic",
            "PROFILE_TITLE": "TLS-Test-Node",
            "TLS_CERT_FILE": str(cert),
            "TLS_KEY_FILE": str(key),
        })

        server_cls = cls.leaf._common.SubscriptionHTTPServer
        cls.previous_context = server_cls.ssl_context
        # build_ssl_context() reads the environment when it is called, not when
        # the module was imported — under systemd the EnvironmentFile is present
        # for the whole process lifetime, so keep the vars set across the call.
        os.environ["TLS_CERT_FILE"] = str(cert)
        os.environ["TLS_KEY_FILE"] = str(key)
        try:
            server_cls.ssl_context = cls.leaf._common.build_ssl_context()
        finally:
            os.environ.pop("TLS_CERT_FILE", None)
            os.environ.pop("TLS_KEY_FILE", None)
        # Fail loudly rather than silently falling back to plain HTTP, which is
        # exactly the regression this class exists to catch.
        assert isinstance(server_cls.ssl_context, ssl.SSLContext)

        cls.server = server_cls(("127.0.0.1", 0), cls.leaf.SubscriptionHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        # Self-signed: verify the transport works, not the (absent) chain of trust.
        cls.client_context = ssl.create_default_context()
        cls.client_context.check_hostname = False
        cls.client_context.verify_mode = ssl.CERT_NONE

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.leaf._common.SubscriptionHTTPServer.ssl_context = cls.previous_context
        cls.tmp.cleanup()

    def test_profile_is_served_over_https(self) -> None:
        request = urllib.request.Request(f"https://127.0.0.1:{self.port}/{TOKEN}/")
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=5, context=self.client_context
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read().decode("utf-8"), PROFILE_BODY)
            self.assertEqual(response.headers["Profile-Title"], "TLS-Test-Node")

    def test_plaintext_request_does_not_crash_the_server(self) -> None:
        """A plain-HTTP probe against the TLS port must be dropped, not fatal."""
        # The server drops the connection mid-handshake, which surfaces as a
        # transport-level error rather than an HTTP response.
        with self.assertRaises((urllib.error.URLError, http.client.HTTPException,
                                ConnectionError)):
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{self.port}/healthz", timeout=5
            )

        # Server still healthy afterwards.
        request = urllib.request.Request(f"https://127.0.0.1:{self.port}/healthz")
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=5, context=self.client_context
        ) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
