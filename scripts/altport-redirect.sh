#!/usr/bin/env bash
# altport-redirect.sh — REDIRECT alternate ports to the real inbound port.
#
# Why alternate ports exist
# -------------------------
# Interference is per-port AND per-carrier, and it changes over weeks. One
# measurement round found every high port dead and 443 the only usable one;
# five weeks later on the same line 443 was the *slowest* (3.8 s vs 1.26 s on
# 8880/40443) while the high ports were fine. Neither result generalises. The
# only robust answer is to expose several ports and let the client's url-test
# race them.
#
# Why REDIRECT instead of extra inbounds
# --------------------------------------
# sing-box config does not change at all, so there is nothing to keep in sync
# and nothing to roll back except one iptables chain. It also means these ports
# never appear in `ss -tlnp` — that is expected, not a fault. And because the
# rewrite happens in nat/PREROUTING, filter/INPUT only ever sees the real port,
# so UFW needs no rule for the alternates.
#
# Idempotent: flushes only the chain it owns before re-adding.
#
# Env:
#   ALT_TCP_PORTS    space/comma separated (e.g. "2096 8880 40443")
#   ALT_UDP_PORTS    space/comma separated (e.g. "2096 8880")
#   TARGET_TCP_PORT  real REALITY inbound port (default 443)
#   TARGET_UDP_PORT  real Hysteria2 inbound port (default = TARGET_TCP_PORT)

set -Eeuo pipefail

TARGET_TCP_PORT="${TARGET_TCP_PORT:-${TARGET_PORT:-443}}"
TARGET_UDP_PORT="${TARGET_UDP_PORT:-$TARGET_TCP_PORT}"
ALT_TCP_PORTS="${ALT_TCP_PORTS//,/ }"
ALT_UDP_PORTS="${ALT_UDP_PORTS//,/ }"
CHAIN=ANYREALITY_ALTPORT

command -v iptables >/dev/null 2>&1 || {
  echo "altport-redirect: iptables not found" >&2
  exit 1
}

# Own chain, hooked from PREROUTING. Flushing PREROUTING wholesale would blow
# away Docker's and everyone else's NAT rules.
iptables -t nat -N "$CHAIN" 2>/dev/null || true
iptables -t nat -F "$CHAIN"
iptables -t nat -C PREROUTING -j "$CHAIN" 2>/dev/null ||
  iptables -t nat -I PREROUTING 1 -j "$CHAIN"

for port in $ALT_TCP_PORTS; do
  [[ "$port" == "$TARGET_TCP_PORT" ]] && continue
  iptables -t nat -A "$CHAIN" -p tcp --dport "$port" -j REDIRECT --to-ports "$TARGET_TCP_PORT"
done
for port in $ALT_UDP_PORTS; do
  [[ "$port" == "$TARGET_UDP_PORT" ]] && continue
  iptables -t nat -A "$CHAIN" -p udp --dport "$port" -j REDIRECT --to-ports "$TARGET_UDP_PORT"
done

# Opportunistically mirror the same REDIRECT rules into ip6tables nat/PREROUTING
# when the kernel supports IPv6 NAT (sing-box listens on "::").
if command -v ip6tables >/dev/null 2>&1 && ip6tables -t nat -L >/dev/null 2>&1; then
  ip6tables -t nat -N "$CHAIN" 2>/dev/null || true
  ip6tables -t nat -F "$CHAIN"
  ip6tables -t nat -C PREROUTING -j "$CHAIN" 2>/dev/null ||
    ip6tables -t nat -I PREROUTING 1 -j "$CHAIN"
  for port in $ALT_TCP_PORTS; do
    [[ "$port" == "$TARGET_TCP_PORT" ]] && continue
    ip6tables -t nat -A "$CHAIN" -p tcp --dport "$port" -j REDIRECT --to-ports "$TARGET_TCP_PORT"
  done
  for port in $ALT_UDP_PORTS; do
    [[ "$port" == "$TARGET_UDP_PORT" ]] && continue
    ip6tables -t nat -A "$CHAIN" -p udp --dport "$port" -j REDIRECT --to-ports "$TARGET_UDP_PORT"
  done
fi

count="$(iptables -t nat -S "$CHAIN" | grep -c -- '-A' || true)"
echo "altport-redirect: $count rule(s) — tcp ${ALT_TCP_PORTS:-none} -> ${TARGET_TCP_PORT}, udp ${ALT_UDP_PORTS:-none} -> ${TARGET_UDP_PORT}"
