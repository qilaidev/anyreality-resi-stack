#!/usr/bin/env python3
"""Reality residential subscription aggregator server.

Lives on the data-center backup node (or anywhere with a stable public IP)
and serves a unified profile listing both the residential leaf and the
data-center node. The profile typically routes Telegram / Discord through
this DC node (which has cleaner messenger reputation) and routes OpenAI /
Anthropic / Netflix through the residential leaf (which earns "real home
user" reputation with those services).

For traffic accounting, this server polls the leaf's ``/status`` endpoint,
caches the result, and falls back to the cached value if the leaf becomes
unreachable — avoiding the "0 bytes used" jitter that would otherwise
confuse the client's usage card.

Routing, environment parsing, and the HTTP server live in ``_common.py``.
All configuration is via environment; see
``templates/env/subscription-aggregator.env.example``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

# _common.py ships next to this file — see the matching note in leaf_server.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
from _common import env_float, env_int, env_str  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aggregator")
_common.set_unit_hint("subscription-aggregator")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = env_int("PORT", "80", minimum=1, maximum=65535)
TOKEN = env_str("TOKEN").strip("/")
FILE_DIR = Path(os.environ.get("FILE_DIR", "/etc/anyreality-resi-stack/files"))
DEFAULT_TARGET = os.environ.get("DEFAULT_TARGET", "profile.yaml")
CACHE_FILE = Path(os.environ.get(
    "CACHE_FILE", "/var/lib/anyreality-resi-stack/usage-cache.json"))
CACHE_TTL_SECONDS = env_float("CACHE_TTL_SECONDS", "60", minimum=5)
REMOTE_POLL_INTERVAL_SECONDS = env_float(
    "REMOTE_POLL_INTERVAL_SECONDS", str(CACHE_TTL_SECONDS), minimum=5
)
TOTAL_BYTES = env_int("TOTAL_BYTES", "0", minimum=0)
FALLBACK_USED_BYTES = env_int("FALLBACK_USED_BYTES", "0")
EXPIRE_TS = env_int("EXPIRE_TS", "0", minimum=0)
PROFILE_TITLE = os.environ.get("PROFILE_TITLE", "Reality-Residential-Dual")
UPDATE_INTERVAL_HOURS = os.environ.get("UPDATE_INTERVAL_HOURS", "24")
REMOTE_STATUS_URL = os.environ.get("REMOTE_STATUS_URL", "").strip()
REMOTE_TIMEOUT_SECONDS = env_float("REMOTE_TIMEOUT_SECONDS", "3", minimum=1)
MAX_REMOTE_STATUS_BYTES = env_int("MAX_REMOTE_STATUS_BYTES", "65536", minimum=1024)
REQUEST_TIMEOUT_SECONDS = env_float("REQUEST_TIMEOUT_SECONDS", "10", minimum=1)

# urlopen() would otherwise accept file:// and read a local path into the
# usage cache, so pin the scheme at startup rather than per request.
if REMOTE_STATUS_URL and urlsplit(REMOTE_STATUS_URL).scheme not in {"http", "https"}:
    _common.config_error(
        f"REMOTE_STATUS_URL must be an http(s) URL, got: {REMOTE_STATUS_URL!r}"
    )

cache_write_lock = threading.Lock()


def read_remote_status() -> dict:
    if not REMOTE_STATUS_URL:
        return {}
    request = Request(
        REMOTE_STATUS_URL,
        headers={"User-Agent": "AnyRealityResiStack-Aggregator/2.1"},
    )
    with urlopen(request, timeout=REMOTE_TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read(MAX_REMOTE_STATUS_BYTES + 1)
    if len(body) > MAX_REMOTE_STATUS_BYTES:
        raise ValueError(
            f"remote status response exceeds MAX_REMOTE_STATUS_BYTES={MAX_REMOTE_STATUS_BYTES}"
        )
    return json.loads(body.decode("utf-8"))


def save_usage_cache(used_bytes: int, status: dict) -> None:
    payload = {
        "reported_used_bytes": used_bytes,
        "remote_status": status,
        "cached_at": int(time.time()),
    }
    with cache_write_lock:
        _common.atomic_write_json(CACHE_FILE, payload)


def read_usage_cache() -> tuple[int, dict] | None:
    if not CACHE_FILE.is_file():
        return None
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        used_bytes = int(payload.get("reported_used_bytes", FALLBACK_USED_BYTES))
        return max(0, used_bytes), payload
    except (OSError, ValueError):
        return None


def current_usage(force_refresh: bool = False) -> tuple[int, dict]:
    """Return (bytes_used, metadata).

    Resolution order: fresh cache → live poll → stale cache → fallback.
    ``force_refresh=True`` skips the freshness check; that is what the
    background poller uses to keep the cache warm so the request path almost
    never has to wait on the leaf.
    """
    cached = read_usage_cache()

    if not force_refresh and cached is not None:
        cached_used, cached_payload = cached
        age = time.time() - int(cached_payload.get("cached_at", 0))
        if age < CACHE_TTL_SECONDS:
            return cached_used, {"source": "cache-fresh", "age": age, "cache": cached_payload}

    try:
        status = read_remote_status()
        reported = int(status.get("reported_used_bytes",
                                  status.get("used_bytes", FALLBACK_USED_BYTES)))
        reported = max(0, reported)
        save_usage_cache(reported, status)
        return reported, {"source": "remote_status", "remote_status": status}
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            cached_used, cached_payload = cached
            return cached_used, {
                "source": "cache-stale-fallback",
                "error": str(exc),
                "cache": cached_payload,
            }
        return max(0, FALLBACK_USED_BYTES), {"source": "fallback", "error": str(exc)}


class AggregatorHandler(_common.BaseSubscriptionHandler):
    server_version = "AnyRealityResiStack-Aggregator/2.1"

    token = TOKEN
    file_dir = FILE_DIR
    default_target = DEFAULT_TARGET
    profile_title = PROFILE_TITLE
    update_interval_hours = UPDATE_INTERVAL_HOURS
    total_bytes = TOTAL_BYTES
    expire_ts = EXPIRE_TS

    def usage_bytes(self) -> int:
        used_bytes, _meta = current_usage()
        return used_bytes

    def status_payload(self) -> dict:
        used_bytes, meta = current_usage()
        return {
            "expire_ts": EXPIRE_TS,
            "poll_interval_seconds": REMOTE_POLL_INTERVAL_SECONDS,
            "profile_title": PROFILE_TITLE,
            "reported_used_bytes": used_bytes,
            "total_bytes": TOTAL_BYTES,
            **meta,
        }


def remote_poll_loop() -> None:
    while True:
        _used_bytes, meta = current_usage(force_refresh=True)
        if meta.get("source") != "remote_status":
            log.warning(
                "remote status poll used %s: %s",
                meta.get("source"),
                meta.get("error", "no error detail"),
            )
        time.sleep(max(5, REMOTE_POLL_INTERVAL_SECONDS))


def start_remote_polling() -> None:
    thread = threading.Thread(target=remote_poll_loop, name="remote-status-poll", daemon=True)
    thread.start()


def startup_preflight() -> None:
    """Warn loudly about conditions that make the service look 'up' but useless."""
    default_profile = FILE_DIR / DEFAULT_TARGET
    if not default_profile.is_file():
        log.warning(
            "DEFAULT_TARGET %s does not exist — the subscription path will answer 404",
            default_profile,
        )
    if not REMOTE_STATUS_URL:
        log.warning(
            "REMOTE_STATUS_URL is empty — usage will always report FALLBACK_USED_BYTES=%s",
            FALLBACK_USED_BYTES,
        )


def main() -> None:
    startup_preflight()
    start_remote_polling()
    _common.serve(HOST, PORT, AggregatorHandler, REQUEST_TIMEOUT_SECONDS)


if __name__ == "__main__":
    main()
