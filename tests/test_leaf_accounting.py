from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAF_PATH = REPO_ROOT / "subscription" / "leaf_server.py"


def load_leaf_module():
    os.environ.setdefault("TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location("leaf_server_under_test", LEAF_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LeafAccountingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.leaf = load_leaf_module()
        self.leaf.STATE_FILE = Path(self.tmp.name) / "usage-state.json"
        self.leaf.USAGE_OFFSET_BYTES = 0
        self.leaf.BILLING_CYCLE_DAY = 1
        self.leaf.COUNT_CURRENT_BOOT_ON_INIT = True
        self.original_current_period_key = self.leaf.current_period_key
        self.leaf.current_period_key = lambda: "2026-05-01"

    def set_counter(self, total: int, boot_id: str = "boot-a") -> None:
        self.leaf.read_total_bytes = lambda: total
        self.leaf.read_boot_id = lambda: boot_id

    def read_state(self) -> dict:
        return json.loads(self.leaf.STATE_FILE.read_text(encoding="utf-8"))

    def test_first_sample_is_baseline(self) -> None:
        self.leaf.COUNT_CURRENT_BOOT_ON_INIT = False
        self.set_counter(1_000)

        used = self.leaf.update_usage_state()

        self.assertEqual(used, 0)
        self.assertEqual(
            self.read_state(),
            {
                "boot_id": "boot-a",
                "last_total": 1_000,
                "period": "2026-05-01",
                "used_bytes": 0,
            },
        )

    def test_first_sample_can_count_current_boot(self) -> None:
        self.set_counter(1_000)

        used = self.leaf.update_usage_state()

        self.assertEqual(used, 1_000)
        self.assertEqual(self.read_state()["used_bytes"], 1_000)

    def test_same_boot_adds_positive_delta(self) -> None:
        self.leaf.COUNT_CURRENT_BOOT_ON_INIT = False
        self.set_counter(1_000)
        self.assertEqual(self.leaf.update_usage_state(), 0)
        self.set_counter(1_400)

        self.assertEqual(self.leaf.update_usage_state(), 400)
        self.assertEqual(self.read_state()["used_bytes"], 400)

    def test_reboot_counts_current_total(self) -> None:
        self.leaf.COUNT_CURRENT_BOOT_ON_INIT = False
        self.set_counter(1_000, "boot-a")
        self.assertEqual(self.leaf.update_usage_state(), 0)
        self.set_counter(50, "boot-b")

        self.assertEqual(self.leaf.update_usage_state(), 50)
        self.set_counter(80, "boot-b")
        self.assertEqual(self.leaf.update_usage_state(), 80)

    def test_month_rollover_keeps_offset(self) -> None:
        self.leaf.STATE_FILE.write_text(
            json.dumps(
                {
                    "boot_id": "boot-a",
                    "last_total": 1_000,
                    "period": "2026-04-01",
                    "used_bytes": 500,
                }
            ),
            encoding="utf-8",
        )
        self.set_counter(1_500, "boot-a")
        self.leaf.USAGE_OFFSET_BYTES = 900

        self.assertEqual(self.leaf.update_usage_state(), 0)
        self.assertEqual(self.leaf.reported_used_bytes(0), 900)
        self.assertEqual(self.read_state()["period"], "2026-05-01")

    def test_corrupt_state_reinitializes(self) -> None:
        self.leaf.COUNT_CURRENT_BOOT_ON_INIT = False
        self.leaf.STATE_FILE.write_text("{not-json", encoding="utf-8")
        self.set_counter(123, "boot-a")

        self.assertEqual(self.leaf.update_usage_state(), 0)
        self.assertEqual(self.read_state()["last_total"], 123)

    def test_custom_billing_cycle_day_period(self) -> None:
        from datetime import datetime

        self.leaf.BILLING_CYCLE_DAY = 11
        self.leaf.current_period_key = self.original_current_period_key

        self.assertEqual(
            self.leaf.current_period_key(datetime(2026, 5, 10, 23, 59)),
            "2026-04-11",
        )
        self.assertEqual(
            self.leaf.current_period_key(datetime(2026, 5, 11, 0, 0)),
            "2026-05-11",
        )

    def test_http_server_limits_abandoned_clients(self) -> None:
        server = self.leaf._common.SubscriptionHTTPServer
        self.assertTrue(server.daemon_threads)
        self.assertEqual(server.request_queue_size, 64)
        self.assertGreater(self.leaf.REQUEST_TIMEOUT_SECONDS, 0)

    def test_counter_sample_uses_state_lock(self) -> None:
        class TrackingLock:
            acquired = False

            def __enter__(self) -> None:
                self.acquired = True

            def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
                self.acquired = False

        tracking_lock = TrackingLock()
        self.leaf.state_lock = tracking_lock

        def read_total_bytes() -> int:
            self.assertTrue(tracking_lock.acquired)
            return 100

        def read_boot_id() -> str:
            self.assertTrue(tracking_lock.acquired)
            return "boot-a"

        self.leaf.read_total_bytes = read_total_bytes
        self.leaf.read_boot_id = read_boot_id

        self.assertEqual(self.leaf.update_usage_state(), 100)

    def test_save_failure_keeps_serving(self) -> None:
        """A full or read-only /var/lib must not turn every profile fetch into a 500.

        Serving the profile is the primary job; the usage counter is secondary,
        so a persistence failure degrades to "counter stops moving".
        """
        self.set_counter(5_000)
        self.assertEqual(self.leaf.update_usage_state(), 5_000)

        def exploding_save(_state: dict) -> None:
            raise OSError(28, "No space left on device")

        self.leaf.save_state = exploding_save
        self.set_counter(9_000)

        # Returns the last persisted value instead of propagating the OSError.
        self.assertEqual(self.leaf.update_usage_state(), 5_000)

    def test_load_failure_returns_zero(self) -> None:
        def exploding_load() -> dict:
            raise OSError("state unreadable")

        self.leaf.load_state = exploding_load
        self.set_counter(1_234)

        self.assertEqual(self.leaf.update_usage_state(), 0)


if __name__ == "__main__":
    unittest.main()
