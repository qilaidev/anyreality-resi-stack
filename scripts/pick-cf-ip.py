#!/usr/bin/env python3
"""Pick CDN edge IPs for the relay path — measured end to end, on YOUR line.

Run this from the client machine whose network you care about, not from the
server. Which edge is good is a property of the *path*, not of the IP: the same
address terminates in Hong Kong for one carrier and in the United States for
another, so a list that is optimal for one line can be the worst choice for the
next one.

Why not just take the lowest handshake RTT
------------------------------------------
Because that measures the wrong leg, and it has produced a confidently wrong
answer twice:

    China Mobile   104.19.63.243  handshake  61.0 ms (fastest)  ->  0.16 Mbps
    China Unicom   104.20.29.23   handshake  89.5 ms (fastest)  ->  108 KB/s (slowest)

A TCP handshake with the edge says nothing about the edge-to-origin leg, and
the origin is where your traffic is actually going. Handshake time is used here
only as a cheap screen to discard the (usually large) majority of ranges that
cannot be reached at all — never for ranking.

Method
------
1. Screen: one TCP connect per sampled address. On a censored line most CDN
   ranges are simply unreachable; one measurement found 15% survived.
2. Rank: for every survivor, fetch a small object from YOUR origin THROUGH that
   edge, in cross-polled rounds (A,B,C,…,A,B,C,… — never all of A then all of
   B). Cross-border jitter reaches whole seconds, so sequential sampling
   reliably invents differences that are not there.
3. Report success rate first, then median time-to-first-byte. If the spread
   *within* a single edge is as large as the difference *between* edges, the
   ranking is noise and this script says so instead of pretending otherwise.

Choose by success rate and by network diversity (different /8s and /16s), not
by shaving milliseconds off a median.

    pick-cf-ip.py --domain example.com                  # full run
    pick-cf-ip.py --domain example.com --screen-only    # how much is reachable
    pick-cf-ip.py --domain example.com --rounds 8       # jittery line

Before trusting any number, make sure the measurement is not going through
your own tunnel: a local TUN interface will happily answer, in about 0.6 ms,
for a server on another continent. Use --interface to bind to the physical NIC,
and check that `curl --noproxy '*' --interface <nic> http://ip.3322.net` returns
your ISP's address and not your node's.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import random
import socket
import ssl
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CF_RANGES_URL = "https://www.cloudflare.com/ips-v4"
CONNECT_TIMEOUT = 3.0
REQUEST_TIMEOUT = 10.0


def fetch_ranges(url: str) -> list[ipaddress.IPv4Network]:
    """Authoritative range list, fetched — never typed from memory.

    A hand-maintained copy used during this project was missing six ranges and
    included addresses that were not the CDN's at all, so most of the scan was
    aimed at nothing.
    """
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
        text = response.read().decode("utf-8")
    return [ipaddress.ip_network(line.strip()) for line in text.split() if line.strip()]


def sample(networks: list[ipaddress.IPv4Network], per_net: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    for net in networks:
        hosts = list(net.hosts())
        if not hosts:
            continue
        for host in rng.sample(hosts, min(per_net, len(hosts))):
            out.append(str(host))
    return out


def _bind_source(sock: socket.socket, interface: str | None) -> None:
    """Force traffic onto a physical NIC, past any local TUN.

    Binding the source *address* is not enough — it does not change routing, so
    the packets still go through the tunnel and the result looks great and
    means nothing.
    """
    if not interface:
        return
    if sys.platform == "darwin":
        # IP_BOUND_IF. Not exposed by the socket module on macOS.
        sock.setsockopt(socket.IPPROTO_IP, 25, socket.if_nametoindex(interface))
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode())


def tcp_handshake_ms(ip: str, port: int, interface: str | None) -> float | None:
    sock = socket.socket()
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        _bind_source(sock, interface)
        start = time.monotonic()
        sock.connect((ip, port))
        return (time.monotonic() - start) * 1000
    except OSError:
        return None
    finally:
        sock.close()


def ttfb_ms(ip: str, port: int, domain: str, path: str, interface: str | None) -> float | None:
    """Time to first byte for a request to `domain` forced through edge `ip`.

    This traverses client -> edge -> origin, so unlike a handshake against the
    edge it actually includes the leg that decides how the tunnel will feel.
    """
    sock = socket.socket()
    sock.settimeout(REQUEST_TIMEOUT)
    context = ssl.create_default_context()
    try:
        _bind_source(sock, interface)
        sock.connect((ip, port))
        with context.wrap_socket(sock, server_hostname=domain) as tls:
            request = (
                f"GET {path} HTTP/1.1\r\nHost: {domain}\r\n"
                "User-Agent: anyreality-pick-cf-ip\r\nConnection: close\r\n\r\n"
            ).encode()
            start = time.monotonic()
            tls.sendall(request)
            first = tls.recv(1)
            if not first:
                return None
            return (time.monotonic() - start) * 1000
    except (OSError, ssl.SSLError):
        return None
    finally:
        with contextlib.suppress(OSError):
            sock.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--domain", required=True, help="the CDN-proxied hostname of your origin")
    ap.add_argument("--path", default="/", help="a small object served by your origin")
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--per-net", type=int, default=6, help="addresses sampled per CDN range")
    ap.add_argument("--rounds", type=int, default=5, help="cross-polled measurement rounds")
    ap.add_argument("--keep", type=int, default=5, help="how many edges to print as the pick")
    ap.add_argument(
        "--interface", default=None, help="physical NIC to bind to (bypasses a local TUN)"
    )
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--seed", type=int, default=1, help="sampling seed (fixed so runs compare)")
    ap.add_argument("--screen-only", action="store_true")
    args = ap.parse_args()

    print(f"fetching {CF_RANGES_URL} …", file=sys.stderr)
    networks = fetch_ranges(CF_RANGES_URL)
    targets = sample(networks, args.per_net, args.seed)
    print(f"{len(networks)} ranges, {len(targets)} sampled addresses", file=sys.stderr)

    print("stage 1: reachability screen …", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        handshakes = list(
            pool.map(lambda ip: (ip, tcp_handshake_ms(ip, args.port, args.interface)), targets)
        )
    alive = [(ip, ms) for ip, ms in handshakes if ms is not None]
    pct = 100 * len(alive) / len(targets) if targets else 0
    print(f"  {len(alive)}/{len(targets)} reachable ({pct:.0f}%)", file=sys.stderr)
    if not alive:
        print("nothing reachable on this line — the CDN path is unusable here", file=sys.stderr)
        return 1
    if args.screen_only:
        for ip, ms in sorted(alive, key=lambda item: item[1]):
            print(f"{ip}\t{ms:.1f} ms")
        print(
            "\nreachability only. Do NOT pick from this list by handshake time — "
            "see the header of this script.",
            file=sys.stderr,
        )
        return 0

    # Keep the screen list to something a cross-polled run can finish, but keep
    # it spread across ranges rather than taking the fastest handshakes: the
    # fastest handshake has twice been the worst end-to-end.
    by_net: dict[str, list[str]] = {}
    for ip, _ in alive:
        key = str(ipaddress.ip_address(ip)).rsplit(".", 2)[0]
        by_net.setdefault(key, []).append(ip)
    shortlist: list[str] = []
    while len(shortlist) < min(24, len(alive)):
        added = False
        for ips in by_net.values():
            if ips:
                shortlist.append(ips.pop())
                added = True
            if len(shortlist) >= 24:
                break
        if not added:
            break

    print(
        f"stage 2: {args.rounds} cross-polled rounds through {len(shortlist)} edges "
        f"to https://{args.domain}{args.path} …",
        file=sys.stderr,
    )
    samples: dict[str, list[float | None]] = {ip: [] for ip in shortlist}
    for round_index in range(args.rounds):
        # Cross-poll: one measurement per edge per round, order reshuffled, so a
        # slow minute penalises every edge equally instead of whichever one
        # happened to be sampled during it.
        order = list(shortlist)
        random.Random(args.seed + round_index).shuffle(order)
        for ip in order:
            samples[ip].append(ttfb_ms(ip, args.port, args.domain, args.path, args.interface))
        print(f"  round {round_index + 1}/{args.rounds}", file=sys.stderr)

    rows = []
    for ip, values in samples.items():
        good = [v for v in values if v is not None]
        if not good:
            continue
        rows.append(
            {
                "ip": ip,
                "ok": len(good),
                "n": len(values),
                "median": statistics.median(good),
                "spread": max(good) - min(good),
            }
        )
    if not rows:
        print("every edge failed end to end — check the origin, not the edges", file=sys.stderr)
        return 1

    # Success rate first, median second. That order is the point: an edge that
    # answers every time at 900 ms is worth more than one that answers three
    # times out of five at 300 ms, because the client re-races on failure.
    rows.sort(key=lambda r: (-r["ok"] / r["n"], r["median"]))

    print(f"\n{'edge':<16}{'ok':>8}{'median TTFB':>14}{'own spread':>13}")
    for row in rows:
        print(
            f"{row['ip']:<16}{row['ok']}/{row['n']:>6}"
            f"{row['median']:>12.0f}ms{row['spread']:>11.0f}ms"
        )

    top = [r for r in rows if r["ok"] == r["n"]] or rows[: args.keep]
    worst_spread = max(r["spread"] for r in top)
    between = max(r["median"] for r in top) - min(r["median"] for r in top)
    print()
    if worst_spread >= between:
        print(
            f"NOISE: the widest spread within one edge ({worst_spread:.0f} ms) is at least the "
            f"difference between edges ({between:.0f} ms). This ranking is not real — choose "
            "from the full-success group by network diversity alone."
        )
    else:
        print(
            f"Signal: between-edge difference {between:.0f} ms exceeds the widest within-edge "
            f"spread ({worst_spread:.0f} ms), so the ordering above is meaningful."
        )

    picked: list[str] = []
    seen_prefix: set[str] = set()
    for row in top:
        prefix = row["ip"].rsplit(".", 2)[0]
        if prefix in seen_prefix:
            continue
        seen_prefix.add(prefix)
        picked.append(row["ip"])
        if len(picked) >= args.keep:
            break

    print("\nSuggested --cdn-ips (one per /16, full success rate first):")
    print("  " + ",".join(picked))
    print(
        "\nBefore dropping an edge you are already using, check whether it is the good one on "
        "somebody else's line — edge assignment follows the path, not the address."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
