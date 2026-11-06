"""Environment parsing must fail with a named variable, not a bare traceback.

Both subscription services run under `Restart=always`. Before these guards a
typo in the EnvironmentFile produced an endless crash loop whose only symptom
was a `KeyError: 'TOKEN'` or `ValueError: invalid literal for int()` in the
journal, with no indication of which unit or which variable was at fault.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(filename: str, alias: str):
    os.environ.setdefault("TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location(alias, REPO_ROOT / "subscription" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


class RenderedOutputTest(unittest.TestCase):
    """No generated artefact may still carry a template placeholder.

    `render_template` used to look for `@@[A-Z_]+@@`, which does not match
    `@@HY2_PASSWORD@@` — so every Hysteria2 token was skipped: not validated,
    not substituted, and the render reported success. The config only failed one
    phase later, in `sing-box check`, with a JSON parse error pointing at a `@`.

    Checking the *output* is the durable form of this test: it does not care
    which pattern the renderer uses or which tokens exist next.
    """

    def test_no_placeholders_survive_into_examples(self) -> None:
        pattern = re.compile(r"@@[A-Za-z0-9_]+@@")
        checked = 0
        for path in sorted((REPO_ROOT / "examples").rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            leftover = sorted(set(pattern.findall(text)))
            self.assertEqual(
                leftover,
                [],
                f"{path.relative_to(REPO_ROOT)} still contains {leftover}",
            )
            checked += 1
        self.assertGreater(checked, 0, "no example files found — did generation run?")


class EnvParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.leaf = load_module("leaf_server.py", "leaf_config_under_test")

    def tearDown(self) -> None:
        os.environ.pop("PROBE", None)

    def test_env_int_accepts_valid_value(self) -> None:
        os.environ["PROBE"] = " 42 "
        self.assertEqual(self.leaf.env_int("PROBE", "0"), 42)

    def test_env_int_uses_default_when_unset(self) -> None:
        self.assertEqual(self.leaf.env_int("PROBE", "7"), 7)

    def test_env_int_rejects_garbage(self) -> None:
        os.environ["PROBE"] = "not-a-number"
        with self.assertRaises(SystemExit) as ctx:
            self.leaf.env_int("PROBE", "0")
        self.assertEqual(ctx.exception.code, 2)

    def test_env_int_enforces_minimum(self) -> None:
        os.environ["PROBE"] = "1"
        with self.assertRaises(SystemExit):
            self.leaf.env_int("PROBE", "60", minimum=5)

    def test_env_float_rejects_garbage(self) -> None:
        os.environ["PROBE"] = "3s"
        with self.assertRaises(SystemExit):
            self.leaf.env_float("PROBE", "3")

    def test_env_str_rejects_empty(self) -> None:
        os.environ["PROBE"] = "   "
        with self.assertRaises(SystemExit):
            self.leaf.env_str("PROBE")

    def test_env_bool_round_trip(self) -> None:
        for raw, expected in (("yes", True), ("0", False), ("TRUE", True), ("off", False)):
            os.environ["PROBE"] = raw
            self.assertIs(self.leaf.env_bool("PROBE", "true"), expected)

    def test_env_bool_rejects_garbage(self) -> None:
        os.environ["PROBE"] = "maybe"
        with self.assertRaises(SystemExit):
            self.leaf.env_bool("PROBE", "true")


if __name__ == "__main__":
    unittest.main()
