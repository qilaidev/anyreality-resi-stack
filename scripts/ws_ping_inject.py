#!/usr/bin/env python3
"""Keep a CDN-proxied WebSocket alive by injecting application-level pings.

The problem
-----------
Cloudflare (and every CDN with the same design) closes a proxied WebSocket
after roughly 100 s with no frames in either direction. TCP keepalive does not
help: it is hop-by-hop and terminates at the edge, so the client's
`tcp_keep_alive` and mihomo's `keep-alive-idle` are both invisible to the CDN.
sing-box's h2mux/smux/yamux do not emit WebSocket-level pings either.

The symptom is distinctive and misleading: connections die at almost exactly
2m05s–2m07s with an EOF, over and over. That looks like a CGNAT reclaim or an
nginx timeout, and chasing either of those wastes days — the origin's
`proxy_read_timeout` was 3600 s the whole time.

The fix
-------
Sit between nginx and sing-box and inject an unmasked WebSocket ping (opcode
0x9, empty payload) toward the CDN whenever the connection has been silent for
PING_EVERY seconds. The CDN sees a frame and resets its idle timer.

    CDN --TLS--> nginx --WS--> THIS(:18444) --TCP--> sing-box(:18443)

Injection has to happen on frame boundaries, so the server-to-client direction
is parsed as a WebSocket frame stream after the HTTP 101 goes past. Writing a
ping into the middle of a partially-forwarded frame would corrupt the stream.

Configuration is via environment (all optional):
    WS_PING_LISTEN_HOST  default 127.0.0.1
    WS_PING_LISTEN_PORT  default 18444
    WS_PING_BACKEND_HOST default 127.0.0.1
    WS_PING_BACKEND_PORT default 18443
    WS_PING_INTERVAL     default 25 (seconds; must stay well under the ~100 s
                         CDN idle timeout)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys

LISTEN_HOST = os.environ.get("WS_PING_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("WS_PING_LISTEN_PORT", "18444"))
BACKEND = (
    os.environ.get("WS_PING_BACKEND_HOST", "127.0.0.1"),
    int(os.environ.get("WS_PING_BACKEND_PORT", "18443")),
)
PING_EVERY = float(os.environ.get("WS_PING_INTERVAL", "25"))
CONNECT_TIMEOUT = float(os.environ.get("WS_PING_CONNECT_TIMEOUT", "10"))

# RFC 6455: FIN=1, opcode=9 (ping), empty payload, unmasked (server-to-client).
WS_PING = b"\x89\x00"
MAX_FRAME = 16 * 1024 * 1024
MAX_HTTP_HEAD = 16384

log = logging.getLogger("ws-ping-inject")


def _set_tcp_nodelay(writer: asyncio.StreamWriter) -> None:
    """Disable Nagle's algorithm on loopback relay sockets to avoid 40ms stalls."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def has_oversized_frame(buf: bytearray) -> bool:
    """Return True if the front of `buf` declares a frame larger than MAX_FRAME."""
    if len(buf) > MAX_FRAME:
        return True
    if len(buf) < 2:
        return False
    length = buf[1] & 0x7F
    header = 2
    if length == 126:
        if len(buf) < 4:
            return False
        length = int.from_bytes(buf[2:4], "big")
        header = 4
    elif length == 127:
        if len(buf) < 10:
            return False
        length = int.from_bytes(buf[2:10], "big")
        header = 10
    if buf[1] & 0x80:
        header += 4
    return (header + length) > MAX_FRAME


def take_ws_frames(buf: bytearray) -> bytes:
    """Detach every complete RFC 6455 frame at the front of `buf`.

    A partial trailing frame stays in the buffer. Returning only whole frames
    is what makes it safe to write a ping right after the returned bytes.
    """
    end = 0
    while True:
        if len(buf) - end < 2:
            break
        length = buf[end + 1] & 0x7F
        header = 2
        if length == 126:
            if len(buf) - end < 4:
                break
            length = int.from_bytes(buf[end + 2 : end + 4], "big")
            header = 4
        elif length == 127:
            if len(buf) - end < 10:
                break
            length = int.from_bytes(buf[end + 2 : end + 10], "big")
            header = 10
        if buf[end + 1] & 0x80:  # masked: 4 more bytes of masking key
            header += 4
        total = header + length
        if total > MAX_FRAME or len(buf) - end < total:
            break
        end += total
    if end == 0:
        return b""
    out = bytes(buf[:end])
    del buf[:end]
    return out


async def _pinger(
    writer: asyncio.StreamWriter,
    lock: asyncio.Lock,
    last: dict,
    upgraded: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    await upgraded.wait()
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
            return
        except asyncio.TimeoutError:
            pass
        if writer.is_closing() or not upgraded.is_set():
            return
        now = loop.time()
        if now - last["t"] < PING_EVERY:
            continue
        try:
            async with lock:
                if not upgraded.is_set():
                    return
                writer.write(WS_PING)
                await writer.drain()
            last["t"] = now
            # debug, not info: one line per ping per connection is ~500
            # journal lines an hour on a handful of idle tunnels.
            log.debug("injected ping")
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            return
        except OSError as exc:
            log.warning("ping failed: %s", exc)
            return


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    _set_tcp_nodelay(client_w)
    try:
        back_r, back_w = await asyncio.wait_for(
            asyncio.open_connection(*BACKEND), timeout=CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("backend %s:%s unreachable: %s", BACKEND[0], BACKEND[1], exc)
        client_w.close()
        with contextlib.suppress(Exception):
            await client_w.wait_closed()
        return
    _set_tcp_nodelay(back_w)

    loop = asyncio.get_running_loop()
    lock = asyncio.Lock()
    last = {"t": loop.time()}
    upgraded = asyncio.Event()
    stop = asyncio.Event()

    async def client_to_backend() -> None:
        try:
            while True:
                data = await client_r.read(65536)
                if not data:
                    break
                last["t"] = loop.time()
                back_w.write(data)
                await back_w.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            stop.set()
            back_w.close()

    async def backend_to_client() -> None:
        head = bytearray()
        frames = bytearray()
        upgraded_seen = False
        passthru = False
        try:
            while True:
                data = await back_r.read(65536)
                if not data:
                    break
                last["t"] = loop.time()
                if passthru:
                    async with lock:
                        client_w.write(data)
                        await client_w.drain()
                    continue
                if not upgraded_seen:
                    head.extend(data)
                    split = head.find(b"\r\n\r\n")
                    if split != -1 and b"101" in head[: head.find(b"\r\n")]:
                        body_at = split + 4
                        async with lock:
                            client_w.write(bytes(head[:body_at]))
                            await client_w.drain()
                        frames.extend(head[body_at:])
                        head.clear()
                        upgraded_seen = True
                        upgraded.set()
                        chunk = take_ws_frames(frames)
                        if chunk:
                            async with lock:
                                client_w.write(chunk)
                                await client_w.drain()
                        if has_oversized_frame(frames):
                            upgraded.clear()
                            passthru = True
                            async with lock:
                                client_w.write(bytes(frames))
                                await client_w.drain()
                            frames.clear()
                    elif split != -1 or len(head) > MAX_HTTP_HEAD:
                        # Not a 101 (an error page, or a response we do not
                        # understand): stop parsing and act as a plain relay.
                        async with lock:
                            client_w.write(bytes(head))
                            await client_w.drain()
                        head.clear()
                        upgraded_seen = True
                        passthru = True  # relay mode; pinger stays idle
                    continue
                frames.extend(data)
                chunk = take_ws_frames(frames)
                if chunk:
                    async with lock:
                        client_w.write(chunk)
                        await client_w.drain()
                if has_oversized_frame(frames):
                    # Bound memory strictly: if a frame header exceeds MAX_FRAME,
                    # fall back to zero-buffer passthrough for this connection
                    # rather than buffering without bound or dropping the stream.
                    upgraded.clear()
                    passthru = True
                    async with lock:
                        client_w.write(bytes(frames))
                        await client_w.drain()
                    frames.clear()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            stop.set()
            client_w.close()

    ping_task = asyncio.create_task(_pinger(client_w, lock, last, upgraded, stop))
    try:
        await asyncio.gather(client_to_backend(), backend_to_client())
    finally:
        ping_task.cancel()
        for writer in (client_w, back_w):
            if not writer.is_closing():
                writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


async def _serve() -> int:
    logging.basicConfig(
        level=os.environ.get("WS_PING_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT, backlog=512)
    log.info(
        "listening %s:%s -> %s:%s, ping every %.0fs",
        LISTEN_HOST,
        LISTEN_PORT,
        BACKEND[0],
        BACKEND[1],
        PING_EVERY,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
        server.close()
        await server.wait_closed()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_serve()))
