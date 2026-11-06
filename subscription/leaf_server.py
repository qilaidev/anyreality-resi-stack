#!/usr/bin/env python3
"""Reality residential subscription leaf server.

Serves a per-token subscription endpoint with three responsibilities:

1.  Hand back the rendered Clash / sing-box / v2rayN profile file under
    ``/<TOKEN>/<filename>`` (or ``/<TOKEN>/`` for the default profile).
2.  Read the kernel network-interface counters to track traffic on a
    per-billing-period basis and emit a ``Subscription-Userinfo`` response header so
    clients can render a usage card.
3.  Expose ``/healthz`` (liveness) and ``/<TOKEN>/status`` (machine-readable
    usage summary) for monitoring and for aggregator nodes to poll.

Routing, environment parsing, and the HTTP server live in ``_common.py``.
All configuration is via environment; see ``templates/env/subscription-leaf.env.example``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time as time_module
from datetime import datetime, time
from pathlib import Path

# _common.py ships next to this file. Anchoring sys.path on the script's own
# directory keeps the import working regardless of cwd, symlinks, or how the
# module is loaded (systemd, a test harness, or a manual run).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
from _common import env_bool, env_float, env_int, env_str  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("leaf")
_common.set_unit_hint("subscription-leaf")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = env_int("PORT", "80", minimum=1, maximum=65535)
TOKEN = env_str("TOKEN").strip("/")
INTERFACE = env_str("INTERFACE", "eth0")
STATE_FILE = Path(os.environ.get(
    "STATE_FILE", "/var/lib/anyreality-resi-stack/usage-state.json"))
TOTAL_BYTES = env_int("TOTAL_BYTES", "0", minimum=0)
USAGE_OFFSET_BYTES = env_int("USAGE_OFFSET_BYTES", "0")
EXPIRE_TS = env_int("EXPIRE_TS", "0", minimum=0)
BILLING_CYCLE_DAY = env_int("BILLING_CYCLE_DAY", "1", minimum=1, maximum=28)
USAGE_POLL_INTERVAL_SECONDS = env_int("USAGE_POLL_INTERVAL_SECONDS", "60", minimum=5)
COUNT_CURRENT_BOOT_ON_INIT = env_bool("COUNT_CURRENT_BOOT_ON_INIT", "true")
PROFILE_TITLE = os.environ.get("PROFILE_TITLE", "Reality-Residential")
UPDATE_INTERVAL_HOURS = os.environ.get("UPDATE_INTERVAL_HOURS", "24")
FILE_DIR = Path(os.environ.get("FILE_DIR", "/etc/anyreality-resi-stack/files"))
DEFAULT_TARGET = os.environ.get("DEFAULT_TARGET", "profile.yaml")
REQUEST_TIMEOUT_SECONDS = env_float("REQUEST_TIMEOUT_SECONDS", "10", minimum=1)

state_lock = threading.Lock()


def read_total_bytes() -> int | None:
    """Sum rx_bytes + tx_bytes for INTERFACE.

    Returns None (rather than crashing the request) if the kernel stats files
    are missing — this happens when INTERFACE was renamed, removed, or when
    running on a non-Linux host. The caller treats None as "skip accounting
    this round" so the server keeps serving the profile file.
    """
    base = Path("/sys/class/net") / INTERFACE / "statistics"
    try:
        with (base / "rx_bytes").open("r", encoding="utf-8") as h:
            rx = int(h.read().strip())
        with (base / "tx_bytes").open("r", encoding="utf-8") as h:
            tx = int(h.read().strip())
        return rx + tx
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        log.warning("read_total_bytes(%s) failed: %s — accounting skipped this round",
                    INTERFACE, exc)
        return None


def read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError):
        return "unknown"


def current_period_key(now: datetime | None = None) -> str:
    """Return the accounting period key.

    BILLING_CYCLE_DAY=1 behaves like a calendar month. Other values anchor the
    period on the provider's billing reset day, e.g. day 11 yields
    ``2026-05-11`` for traffic between May 11 and June 10.
    """
    now = now or datetime.now()
    day = min(max(BILLING_CYCLE_DAY, 1), 28)
    year = now.year
    month = now.month
    if now.day < day:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def next_billing_reset_ts(now: datetime | None = None) -> int:
    now = now or datetime.now()
    day = min(max(BILLING_CYCLE_DAY, 1), 28)
    year = now.year
    month = now.month
    if now.day >= day:
        month += 1
        if month == 13:
            month = 1
            year += 1
    reset_at = datetime.combine(datetime(year, month, day).date(), time.min)
    return int(reset_at.timestamp())


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("load_state(%s) failed: %s — reinitializing accounting state", STATE_FILE, exc)
        return {}


def save_state(state: dict) -> None:
    _common.atomic_write_json(STATE_FILE, state)


def update_usage_state() -> int:
    """Accounting wrapper that never raises.

    Serving the profile file is this server's primary job; the usage counter is
    secondary. A full disk or a read-only ``/var/lib`` must therefore degrade to
    "counter stops moving", not to a 500 that breaks every client's
    subscription refresh.
    """
    try:
        return _compute_usage_state()
    except Exception as exc:  # noqa: BLE001
        log.warning("usage accounting failed: %s — serving last known counter", exc)
        try:
            return int(load_state().get("used_bytes", 0))
        except Exception:  # noqa: BLE001
            return 0


def _compute_usage_state() -> int:
    """Maintain a monotonically increasing billing-period counter despite reboots.

    If the kernel stats are unavailable this round, return the last persisted
    value without modifying state — the next round will try again.
    """
    with state_lock:
        current_total = read_total_bytes()
        if current_total is None:
            state = load_state()
            return int(state.get("used_bytes", 0)) if state else 0

        current_boot = read_boot_id()
        period_key = current_period_key()
        state = load_state()
        if not state:
            state = {
                "boot_id": current_boot,
                "last_total": current_total,
                "period": period_key,
                "used_bytes": current_total if COUNT_CURRENT_BOOT_ON_INIT else 0,
            }
            save_state(state)
            return int(state["used_bytes"])

        state_period = state.get("period", state.get("month"))
        if state_period != period_key:
            state = {
                "boot_id": current_boot,
                "last_total": current_total,
                "period": period_key,
                "used_bytes": 0,
            }
            save_state(state)
            return 0

        last_total = int(state.get("last_total", 0))
        used_bytes = int(state.get("used_bytes", 0))
        last_boot = state.get("boot_id", "")

        # Same boot, counter has not wrapped: add only the delta.
        if current_boot == last_boot and current_total >= last_total:
            used_bytes += current_total - last_total
        else:
            # Reboot, counter rollover, or restored state: kernel counters
            # restarted from a lower baseline, so count the current boot total.
            used_bytes += current_total

        state["boot_id"] = current_boot
        state["last_total"] = current_total
        state["period"] = period_key
        state.pop("month", None)
        state["used_bytes"] = used_bytes
        save_state(state)
        return used_bytes


def reported_used_bytes(used_bytes: int) -> int:
    return max(0, USAGE_OFFSET_BYTES + used_bytes)


class SubscriptionHandler(_common.BaseSubscriptionHandler):
    server_version = "AnyRealityResiStack-Leaf/2.1"

    token = TOKEN
    file_dir = FILE_DIR
    default_target = DEFAULT_TARGET
    profile_title = PROFILE_TITLE
    update_interval_hours = UPDATE_INTERVAL_HOURS
    total_bytes = TOTAL_BYTES
    expire_ts = EXPIRE_TS

    def usage_bytes(self) -> int:
        return reported_used_bytes(update_usage_state())

    def status_payload(self) -> dict:
        used_bytes = update_usage_state()
        return {
            "billing_cycle_day": BILLING_CYCLE_DAY,
            "billing_reset_ts": next_billing_reset_ts(),
            "counter_used_bytes": used_bytes,
            "count_current_boot_on_init": COUNT_CURRENT_BOOT_ON_INIT,
            "expire_ts": EXPIRE_TS,
            "interface": INTERFACE,
            "period": current_period_key(),
            "poll_interval_seconds": USAGE_POLL_INTERVAL_SECONDS,
            "profile_title": PROFILE_TITLE,
            "reported_used_bytes": reported_used_bytes(used_bytes),
            "total_bytes": TOTAL_BYTES,
            "usage_offset_bytes": USAGE_OFFSET_BYTES,
            "used_bytes": used_bytes,
        }


def usage_poll_loop() -> None:
    while True:
        update_usage_state()
        time_module.sleep(max(5, USAGE_POLL_INTERVAL_SECONDS))


def start_usage_polling() -> None:
    thread = threading.Thread(target=usage_poll_loop, name="usage-poll", daemon=True)
    thread.start()


def startup_preflight() -> None:
    """Warn loudly about conditions that make the service look 'up' but useless."""
    default_profile = FILE_DIR / DEFAULT_TARGET
    if not default_profile.is_file():
        log.warning(
            "DEFAULT_TARGET %s does not exist — the subscription path will answer 404",
            default_profile,
        )
    if not (Path("/sys/class/net") / INTERFACE).exists():
        log.warning(
            "INTERFACE %s not found under /sys/class/net — traffic accounting will stay at 0",
            INTERFACE,
        )


def main() -> None:
    startup_preflight()
    start_usage_polling()
    _common.serve(HOST, PORT, SubscriptionHandler, REQUEST_TIMEOUT_SECONDS)


if __name__ == "__main__":
    main()
