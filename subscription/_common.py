#!/usr/bin/env python3
"""Shared plumbing for the leaf and aggregator subscription servers.

The two servers differ in exactly two ways: where the usage number comes from
(kernel counters vs. a polled upstream) and what their ``/status`` JSON says.
Everything else — environment parsing, path safety, content types, the
``Content-Disposition`` shape, the HTTP server, the request routing — was
duplicated line-for-line, which is how the two copies drifted apart (different
``ensure_ascii`` on the health payload, for one).

This module holds the common half. It is deployed alongside the two server
scripts in the same directory, so a plain ``import _common`` resolves via
``sys.path[0]`` with no packaging, no ``PYTHONPATH``, and no dependencies —
the zero-dependency property of this package is deliberate and preserved.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import ssl
import threading
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NoReturn
from urllib.parse import parse_qs, quote, unquote

log = logging.getLogger("subscription")

CONTENT_TYPES = {
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


# ── Configuration parsing ────────────────────────────────────────────────
# Both services run under `Restart=always`. A typo in the EnvironmentFile used
# to surface as a bare KeyError/ValueError traceback in an endless crash loop
# with no indication of which unit or which variable was at fault. Parse
# defensively instead and exit 2 with the offending variable named.
_UNIT_HINT = "the subscription service"


def set_unit_hint(unit: str) -> None:
    """Name the systemd unit so configuration errors are directly actionable."""
    global _UNIT_HINT
    _UNIT_HINT = unit


def config_error(message: str) -> NoReturn:
    log.error("configuration error: %s", message)
    log.error("check the EnvironmentFile, then: systemctl restart %s", _UNIT_HINT)
    raise SystemExit(2)


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or not value.strip():
        config_error(f"{name} is required but empty or unset")
    return value


def env_int(name: str, default: str, minimum: int | None = None,
            maximum: int | None = None) -> int:
    raw = os.environ.get(name, default).strip()
    try:
        value = int(raw)
    except ValueError:
        config_error(f"{name} must be an integer, got: {raw!r}")
    if minimum is not None and value < minimum:
        config_error(f"{name} must be >= {minimum}, got: {value}")
    if maximum is not None and value > maximum:
        config_error(f"{name} must be <= {maximum}, got: {value}")
    return value


def env_float(name: str, default: str, minimum: float | None = None) -> float:
    raw = os.environ.get(name, default).strip()
    try:
        value = float(raw)
    except ValueError:
        config_error(f"{name} must be a number, got: {raw!r}")
    if minimum is not None and value < minimum:
        config_error(f"{name} must be >= {minimum}, got: {value}")
    return value


def env_bool(name: str, default: str) -> bool:
    raw = os.environ.get(name, default).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    config_error(f"{name} must be true/false, got: {raw!r}")


# ── Filesystem helpers ───────────────────────────────────────────────────
def safe_target_path(target: str, file_dir: Path, default_target: str) -> Path | None:
    """Resolve ``target`` inside ``file_dir`` while rejecting traversal.

    Only bare, non-hidden filenames are accepted. Note that pathlib does NOT
    normalise ``..`` away — ``Path("..").name`` is ``".."`` — so the separator
    check alone would happily return ``file_dir/..``. Today that resolves to a
    directory and fails the caller's ``is_file()`` guard, but relying on that is
    one refactor away from a real traversal, so reject the dot entries here.
    """
    target = target.strip("/")
    if not target:
        target = default_target
    if target.startswith(".") or target != Path(target).name:
        return None
    return file_dir / target


# Client families and the profile format each one can actually parse. Matching
# is substring, lowercase, longest-prefix-irrelevant — user agents in this space
# are inconsistent enough that anything stricter misfires.
CLASH_AGENTS = ("clash", "mihomo", "meta", "stash", "flclash", "clashx")
SINGBOX_AGENTS = (
    "sing-box", "singbox", "sfa", "sfi", "sfm", "karing", "hiddify", "nekobox", "nekoray",
)
URI_AGENTS = (
    "shadowrocket", "v2rayn", "v2rayng", "streisand", "v2box", "quantumult", "loon",
)

FORMAT_TARGETS = {
    "singbox": "profile.json",
    "sing-box": "profile.json",
    "json": "profile.json",
    "clash": "profile.yaml",
    "mihomo": "profile.yaml",
    "yaml": "profile.yaml",
    "uris": "profile.txt",
    "uri": "profile.txt",
    "base64": "profile.txt",
    "txt": "profile.txt",
}


def profile_for_user_agent(user_agent: str, file_dir: Path, default_target: str) -> str:
    """Pick the profile format a client can parse, from its User-Agent.

    Handing every client one canonical format means half of them get a file
    they cannot read — and the failure is silent on the server: the request is
    a 200, the client just shows an empty or broken profile. Serving one URL
    that adapts is what lets a household mix sing-box phones, Clash desktops,
    and Shadowrocket/v2rayN URI clients without anybody having to know which
    URL is theirs.

    Falls back to ``default_target`` for anything unrecognised (including
    browsers and curl), so an unknown client behaves# exactly as before.
    """
    agent = (user_agent or "").lower()
    # Clash first: several mihomo forks put "sing-box" in the UA as a
    # compatibility claim while still only parsing YAML.
    for needle in CLASH_AGENTS:
        if needle in agent:
            candidate = file_dir / "profile.yaml"
            return candidate.name if candidate.is_file() else default_target
    for needle in SINGBOX_AGENTS:
        if needle in agent:
            candidate = file_dir / "profile.json"
            return candidate.name if candidate.is_file() else default_target
    for needle in URI_AGENTS:
        if needle in agent:
            candidate = file_dir / "profile.txt"
            return candidate.name if candidate.is_file() else default_target
    return default_target


# Cache of gzip-compressed profile bodies, keyed by (path, mtime, size).
# The profiles are static between rebuilds and are measured in megabytes, so
# compressing on every request would burn CPU on a 1-vCPU box for no reason —
# and clients poll on a timer.
_GZIP_CACHE: dict[tuple[str, int, int], bytes] = {}
_GZIP_CACHE_MAX = 4
# Below roughly a kilobyte the gzip header costs more than it saves.
_GZIP_MIN_BYTES = 1024


def wants_gzip(accept_encoding: str) -> bool:
    """True when the client advertised gzip.

    Deliberately simple: the header is a client hint, and every proxy client in
    scope either sends `gzip` or sends nothing. A quality value of 0 ("gzip;q=0"
    means *do not*) is the one case worth honouring.
    """
    for part in (accept_encoding or "").split(","):
        token, _, params = part.strip().partition(";")
        if token.strip().lower() not in ("gzip", "*"):
            continue
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    if float(value) == 0:
                        return False
                except ValueError:
                    pass
        return True
    return False


def gzipped(path: Path, body: bytes) -> bytes:
    """Compressed form of ``body``, cached per file version.

    Why this exists: a full profile with the routing rules inlined is a few
    hundred kilobytes to a few megabytes, and it is re-downloaded by every
    client on every subscription refresh — over exactly the congested,
    lossy links this project exists for. Compression is roughly a 6x
    reduction and it is the difference between an update that completes and
    one that times out half-way.
    """
    try:
        stat = path.stat()
        key = (str(path), int(stat.st_mtime), stat.st_size)
    except OSError:
        key = (str(path), 0, len(body))
    cached = _GZIP_CACHE.get(key)
    if cached is not None:
        return cached
    # mtime=0 so the same profile always compresses to the same bytes; a
    # timestamp in the gzip header would make every response differ.
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as handle:
        handle.write(body)
    compressed = buffer.getvalue()
    if len(_GZIP_CACHE) >= _GZIP_CACHE_MAX:
        _GZIP_CACHE.clear()
    _GZIP_CACHE[key] = compressed
    return compressed


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def content_disposition_for(name: str) -> str:
    """Build an RFC 6266 / RFC 5987 Content-Disposition value.

    Clients that cannot parse the header fall back to inventing a numeric id
    for the imported profile, so emit BOTH forms: a plain ASCII ``filename=``
    that every client understands, and a percent-encoded ``filename*=`` that
    carries the exact (possibly non-ASCII) name for clients that do.
    """
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write ``payload`` to ``path`` atomically.

    The temp file is created alongside the target (never in /tmp) so the final
    ``replace`` is a same-filesystem rename, and is uniquely named per
    process/thread so concurrent writers cannot clobber each other's temp file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()


# ── HTTP ─────────────────────────────────────────────────────────────────
class SubscriptionHTTPServer(ThreadingHTTPServer):
    """Threaded server with a per-connection timeout and optional TLS.

    ``request_timeout`` keeps slow or abandoned clients from pinning a worker
    thread forever. ``ssl_context`` is set when TLS_CERT_FILE is configured; a
    failed handshake raises inside ``get_request``, which ``serve_forever``
    already treats as a dropped connection, so a probe cannot take the server
    down.
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64
    request_timeout = 10.0
    ssl_context: ssl.SSLContext | None = None

    def get_request(self):  # type: ignore[no-untyped-def]
        sock, addr = super().get_request()
        sock.settimeout(self.request_timeout)
        if self.ssl_context is not None:
            sock = self.ssl_context.wrap_socket(sock, server_side=True)
        return sock, addr


def build_ssl_context() -> ssl.SSLContext | None:
    """Build a TLS context from TLS_CERT_FILE / TLS_KEY_FILE, or None.

    The subscription URL is a credential — the profile behind it contains the
    node password — so serving it over plain HTTP exposes it to anyone on the
    path. Terminating TLS here needs a certificate for a real hostname, which
    an IP-only deployment does not have; hence opt-in rather than default.
    """
    cert = os.environ.get("TLS_CERT_FILE", "").strip()
    key = os.environ.get("TLS_KEY_FILE", "").strip()
    if not cert and not key:
        return None
    if not cert or not key:
        config_error("TLS_CERT_FILE and TLS_KEY_FILE must both be set, or neither")
    for label, path in (("TLS_CERT_FILE", cert), ("TLS_KEY_FILE", key)):
        if not Path(path).is_file():
            config_error(f"{label} does not exist or is not a file: {path}")

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
    except (ssl.SSLError, OSError) as exc:
        config_error(f"cannot load TLS certificate/key ({exc})")
    log.info("TLS enabled using %s", cert)
    return context


def serve(host: str, port: int, handler: type[BaseHTTPRequestHandler],
          request_timeout: float) -> NoReturn:
    """Bind and serve forever, turning a failed bind into a named config error."""
    SubscriptionHTTPServer.request_timeout = request_timeout
    SubscriptionHTTPServer.ssl_context = build_ssl_context()
    try:
        server = SubscriptionHTTPServer((host, port), handler)
    except OSError as exc:
        config_error(f"cannot bind {host}:{port} ({exc}) — port busy or missing privileges")
    scheme = "https" if SubscriptionHTTPServer.ssl_context else "http"
    log.info("listening on %s://%s:%s", scheme, host, port)
    server.serve_forever()
    raise SystemExit(0)


class BaseSubscriptionHandler(BaseHTTPRequestHandler):
    """Routing shared by both servers.

    Subclasses provide the two things that actually differ:
    ``usage_bytes()`` and ``status_payload()``. Everything below — the token
    check, path safety, headers, HEAD handling — stays in one place so the two
    deployments cannot drift apart again.
    """

    # Set by the concrete server module before the server starts.
    token = ""
    file_dir = Path("/etc/anyreality-resi-stack/files")
    default_target = "profile.yaml"
    profile_title = ""
    update_interval_hours = "24"
    total_bytes = 0
    expire_ts = 0

    def usage_bytes(self) -> int:
        raise NotImplementedError

    def status_payload(self) -> dict:
        raise NotImplementedError

    def do_GET(self) -> None:  # noqa: N802
        self.handle_request(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self.handle_request(send_body=False)

    def handle_request(self, send_body: bool) -> None:
        path_part, _, query_part = self.path.partition("?")
        raw_path = unquote(path_part).strip("/")

        if raw_path == "healthz":
            self.send_json(HTTPStatus.OK, {"ok": True, "service": self.profile_title}, send_body)
            return

        parts = raw_path.split("/", 1) if raw_path else []
        if not parts or parts[0] != self.token:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if len(parts) == 1 or not parts[1]:
            # Bare /<TOKEN>/ — check for an explicit ?format= override first,
            # then decide the format from the client User-Agent so one URL
            # serves all three ecosystems. An explicit filename always wins.
            fmt_values = parse_qs(query_part).get("format", [])
            fmt_target = FORMAT_TARGETS.get(fmt_values[0].strip().lower()) if fmt_values else None
            if fmt_target and (self.file_dir / fmt_target).is_file():
                target = fmt_target
            else:
                target = profile_for_user_agent(
                    self.headers.get("User-Agent", ""), self.file_dir, self.default_target
                )
        else:
            target = parts[1]
        if target == "status":
            self.send_json(HTTPStatus.OK, self.status_payload(), send_body)
            return

        file_path = safe_target_path(target, self.file_dir, self.default_target)
        if file_path is None or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = file_path.read_bytes()
        used_bytes = self.usage_bytes()

        # Compress when the client asked. Content-Length must describe what is
        # actually on the wire, including for HEAD — a HEAD that advertises the
        # uncompressed length makes clients that pre-allocate from it truncate
        # the real download.
        encoding = None
        if len(body) >= _GZIP_MIN_BYTES and wants_gzip(
            self.headers.get("Accept-Encoding", "")
        ):
            body = gzipped(file_path, body)
            encoding = "gzip"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type_for(file_path))
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            # The body varies by request header, so anything caching in front of
            # this must key on it.
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Profile-Title", self.profile_title)
        self.send_header("Profile-Update-Interval", self.update_interval_hours)
        self.send_header("Content-Disposition", content_disposition_for(file_path.name))
        self.send_header(
            "Subscription-Userinfo",
            f"upload=0; download={used_bytes}; total={self.total_bytes}; "
            f"expire={self.expire_ts}",
        )
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def send_json(self, status: HTTPStatus, payload: dict, send_body: bool) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.info("%s - %s", self.address_string(), fmt % args)
