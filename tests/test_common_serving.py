"""Coverage for the shared serving layer: path safety, atomic writes, TLS.

``safe_target_path`` is the only thing standing between a token holder and
arbitrary file reads on the host — anything under ``FILE_DIR`` is public under
the token path, and anything outside it must be unreachable.
"""

from __future__ import annotations

import importlib.util
import json
import os
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_common():
    os.environ.setdefault("TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location(
        "common_serving_under_test", REPO_ROOT / "subscription" / "_common.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SafeTargetPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_common()
        cls.file_dir = Path("/etc/anyreality-resi-stack/files")

    def resolve(self, target: str):
        return self.common.safe_target_path(target, self.file_dir, "profile.json")

    def test_plain_filename_resolves_inside_file_dir(self) -> None:
        self.assertEqual(self.resolve("profile.json"), self.file_dir / "profile.json")

    def test_empty_target_falls_back_to_default(self) -> None:
        self.assertEqual(self.resolve(""), self.file_dir / "profile.json")
        self.assertEqual(self.resolve("/"), self.file_dir / "profile.json")

    def test_traversal_is_rejected(self) -> None:
        for evil in (
            "../secrets.env",
            "../../etc/shadow",
            "sub/dir/profile.json",
            "..",
            "./profile.json",
        ):
            with self.subTest(target=evil):
                self.assertIsNone(self.resolve(evil))

    def test_absolute_path_is_rejected(self) -> None:
        # Leading slashes are stripped, so an absolute path degrades to a
        # relative one — which must still be rejected for having separators.
        self.assertIsNone(self.resolve("/etc/passwd"))


class AtomicWriteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_common()

    def test_write_is_readable_and_leaves_no_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "state.json"
            self.common.atomic_write_json(target, {"used_bytes": 42})

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                             {"used_bytes": 42})
            leftovers = [p.name for p in target.parent.iterdir() if p.name != target.name]
            self.assertEqual(leftovers, [])

    def test_temp_file_is_on_the_target_filesystem(self) -> None:
        """The replace must be a same-directory rename, not a cross-device copy."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            observed: list[Path] = []
            original = Path.replace

            def spy(self_path, dst):  # noqa: ANN001
                observed.append(Path(self_path).parent)
                return original(self_path, dst)

            Path.replace = spy  # type: ignore[method-assign]
            try:
                self.common.atomic_write_json(target, {"a": 1})
            finally:
                Path.replace = original  # type: ignore[method-assign]

            self.assertEqual(observed, [target.parent])


class TLSContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_common()

    def setUp(self) -> None:
        for name in ("TLS_CERT_FILE", "TLS_KEY_FILE"):
            os.environ.pop(name, None)
        self.addCleanup(lambda: [os.environ.pop(n, None)
                                 for n in ("TLS_CERT_FILE", "TLS_KEY_FILE")])

    def test_no_tls_configured_returns_none(self) -> None:
        self.assertIsNone(self.common.build_ssl_context())

    def test_half_configured_tls_is_a_config_error(self) -> None:
        os.environ["TLS_CERT_FILE"] = "/tmp/does-not-matter.pem"
        with self.assertRaises(SystemExit) as ctx:
            self.common.build_ssl_context()
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_cert_file_is_a_config_error(self) -> None:
        os.environ["TLS_CERT_FILE"] = "/nonexistent/cert.pem"
        os.environ["TLS_KEY_FILE"] = "/nonexistent/key.pem"
        with self.assertRaises(SystemExit):
            self.common.build_ssl_context()

    def test_valid_certificate_builds_a_context(self) -> None:
        if not shutil_which("openssl"):
            self.skipTest("openssl not available")
        with tempfile.TemporaryDirectory() as tmp:
            cert = Path(tmp) / "cert.pem"
            key = Path(tmp) / "key.pem"
            result = subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(cert), "-days", "1",
                 "-subj", "/CN=localhost"],
                capture_output=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest("openssl could not generate a test certificate")

            os.environ["TLS_CERT_FILE"] = str(cert)
            os.environ["TLS_KEY_FILE"] = str(key)
            context = self.common.build_ssl_context()

            self.assertIsInstance(context, ssl.SSLContext)
            self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    unittest.main()
