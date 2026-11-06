from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION_DIR = REPO_ROOT / "subscription"


def load_module(filename: str, alias: str):
    os.environ.setdefault("TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location(alias, SUBSCRIPTION_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


class ContentDispositionTest(unittest.TestCase):
    """Clients that cannot parse Content-Disposition invent a numeric profile
    id instead of using the real filename, so both the plain ASCII form and the
    RFC 5987 encoded form must always be present."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_module("_common.py", "common_cd_under_test")

    def test_ascii_filename_has_both_forms(self) -> None:
        value = self.common.content_disposition_for("profile.json")
        self.assertEqual(
            value,
            "attachment; filename=\"profile.json\"; filename*=UTF-8''profile.json",
        )

    def test_non_ascii_filename_is_percent_encoded(self) -> None:
        value = self.common.content_disposition_for("香港节点.json")
        self.assertIn("filename*=UTF-8''%E9%A6%99%E6%B8%AF", value)
        # The ASCII fallback must stay pure ASCII or the header is unsendable.
        head = value.split(";")[1]
        head.encode("ascii")

    def test_quote_cannot_escape_ascii_form(self) -> None:
        value = self.common.content_disposition_for('a"b.json')
        self.assertNotIn('"a"b.json"', value)
        self.assertIn('filename="a_b.json"', value)


class SharedImplementationTest(unittest.TestCase):
    """Both servers must route through the shared handler.

    The leaf and aggregator used to carry line-for-line copies of the routing,
    header, and path-safety code, which is exactly how they drifted apart. If a
    future change reintroduces a private copy, these assertions fail.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_module("_common.py", "common_shared_under_test")
        cls.leaf = load_module("leaf_server.py", "leaf_shared_under_test")
        cls.aggregator = load_module("aggregator_server.py", "aggregator_shared_under_test")

    def test_handlers_share_the_base_class(self) -> None:
        base = self.leaf._common.BaseSubscriptionHandler
        self.assertTrue(issubclass(self.leaf.SubscriptionHandler, base))
        self.assertTrue(issubclass(self.aggregator.AggregatorHandler, base))

    def test_both_servers_load_the_same_common_module(self) -> None:
        self.assertIs(self.leaf._common, self.aggregator._common)

    def test_handlers_expose_distinct_server_versions(self) -> None:
        self.assertIn("Leaf", self.leaf.SubscriptionHandler.server_version)
        self.assertIn("Aggregator", self.aggregator.AggregatorHandler.server_version)


if __name__ == "__main__":
    unittest.main()
