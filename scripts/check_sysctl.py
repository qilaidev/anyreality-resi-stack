#!/usr/bin/env python3
"""Assert the *effective* value of the kernel parameters that matter.

Never check the file. `/etc/sysctl.d/` is loaded in filename order and later
files silently override earlier ones. A host audited here once had five
`99-*.conf` files with fourteen keys defined more than once — including
`tcp_congestion_control` in two of them. Editing the "obvious" file and seeing
no effect was the guaranteed outcome, with nothing anywhere to indicate why.

This is the same shape of trap as an nginx `sites-enabled` symlink replaced by
a regular file: the edit looks applied and is not. The rule that falls out of
it is general — verify runtime state, not the file you edited:

    nginx     ->  nginx -T | grep <key>        (not `nginx -t`)
    sysctl    ->  sysctl -n <key>              (not the .conf)
    sing-box  ->  start it and check behaviour (not `sing-box check`)

Exit 0 when every parameter holds, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys

# key -> (comparison, expected)
EXPECT: dict[str, tuple[str, object]] = {
    "net.ipv4.tcp_congestion_control": ("eq", "bbr"),
    "net.core.default_qdisc": ("eq", "fq"),
    # Long-lived proxy tunnels go idle between bursts. With this at 1 the
    # congestion window is reset after every idle period and each burst
    # restarts from slow start — on a 200 ms path that is very visible.
    "net.ipv4.tcp_slow_start_after_idle": ("eq", "0"),
    # Cross-border BDP: ~200 ms RTT at 1 Gbps is ~25 MB in flight. Default
    # buffers cap throughput long before the link does.
    "net.core.rmem_max": ("ge", 16777216),
    "net.core.wmem_max": ("ge", 16777216),
    "net.ipv4.udp_rmem_min": ("ge", 16384),
    "net.ipv4.udp_wmem_min": ("ge", 16384),
    # Domestic CGNAT reclaims idle TCP mappings in 30–90 s. Keepalives have to
    # be more frequent than that or every idle tunnel comes back dead.
    "net.ipv4.tcp_keepalive_time": ("le", 90),
}


def read(key: str) -> str | None:
    result = subprocess.run(
        ["sysctl", "-n", key], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    bad: list[str] = []
    for key, (op, want) in EXPECT.items():
        value = read(key)
        if value is None:
            bad.append(f"{key}: unreadable")
            continue
        if op == "eq":
            if value != want:
                bad.append(f"{key}={value} (want {want})")
            continue
        try:
            number = int(value)
        except ValueError:
            bad.append(f"{key}={value} is not numeric")
            continue
        if op == "ge" and number < want:  # type: ignore[operator]
            bad.append(f"{key}={value} (want >= {want})")
        if op == "le" and number > want:  # type: ignore[operator]
            bad.append(f"{key}={value} (want <= {want})")

    if bad:
        print("; ".join(bad))
        print(
            "A later /etc/sysctl.d/ file most likely overrides an earlier one — "
            "check with: grep -rn '<key>' /etc/sysctl.d/ | sort"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
