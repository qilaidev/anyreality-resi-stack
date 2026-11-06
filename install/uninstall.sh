#!/usr/bin/env bash
# uninstall.sh — stop services, remove units, optionally keep secrets/backups.
# Does NOT remove sing-box binary (apt-managed; uninstall manually if desired).

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export REPO_ROOT
COMMON_SH_LOADED=1
export COMMON_SH_LOADED
# shellcheck source=lib/common.sh
. "$REPO_ROOT/install/lib/common.sh"

require_root

KEEP_SECRETS=1
KEEP_BACKUPS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-secrets)
      KEEP_SECRETS=0
      shift
      ;;
    --purge-backups)
      KEEP_BACKUPS=0
      shift
      ;;
    --purge-all)
      KEEP_SECRETS=0
      KEEP_BACKUPS=0
      shift
      ;;
    *) die "Unknown arg: $1" ;;
  esac
done

# Record the inbound port before the sing-box config is deleted, so the UFW
# cleanup below can remove the rule this installer actually created rather
# than assuming 443.
INBOUND_PORT="$(
  grep -ho '"listen_port"[[:space:]]*:[[:space:]]*[0-9]\+' \
    /etc/sing-box/conf/11_*.json 2>/dev/null |
    grep -o '[0-9]\+' | head -1
)"
INBOUND_PORT="${INBOUND_PORT:-443}"

step "Stopping and disabling services"
# The reality-resi-stack-backup.* entries clean up hosts that predate the
# rename to anyreality-resi-stack and never went through the migration phase.
for svc in sing-box subscription-leaf subscription-aggregator \
  ws-ping-inject altport-redirect refresh-rulesets.timer warp-watchdog.timer \
  anyreality-resi-stack-backup.timer reality-resi-stack-backup.timer; do
  systemctl is-enabled --quiet "$svc" 2>/dev/null && run systemctl disable --now "$svc" || true
done

step "Removing systemd units"
for unit in sing-box.service \
  subscription-leaf.service \
  subscription-aggregator.service \
  ws-ping-inject.service \
  altport-redirect.service \
  refresh-rulesets.service \
  refresh-rulesets.timer \
  warp-watchdog.service \
  warp-watchdog.timer \
  anyreality-resi-stack-backup.service \
  anyreality-resi-stack-backup.timer \
  reality-resi-stack-backup.service \
  reality-resi-stack-backup.timer; do
  # `[[ … ]] && rm` as the loop body makes the whole loop exit non-zero when the
  # last unit is absent, which `set -e` then turns into an aborted uninstall.
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    run rm -f "/etc/systemd/system/$unit"
  fi
done
run systemctl daemon-reload

step "Removing config and runtime"
run rm -rf /etc/sing-box/conf /etc/sing-box/logs
run rm -rf /usr/local/lib/anyreality-resi-stack /usr/local/lib/reality-resi-stack
run rm -f /usr/local/sbin/backup-anyreality-resi-stack.sh /usr/local/sbin/backup-reality-resi-stack.sh
run rm -f /usr/local/sbin/anyreality-resi-stack-healthcheck \
  /usr/local/sbin/anyreality-resi-stack-rotate-sub-token \
  /usr/local/sbin/anyreality-resi-stack-warp
run rm -f /etc/logrotate.d/sing-box
run rm -rf /run/anyreality-warp-watchdog
run rm -rf /var/lib/anyreality-resi-stack/usage-state.json /var/lib/anyreality-resi-stack/usage-cache.json \
  /var/lib/reality-resi-stack/usage-state.json /var/lib/reality-resi-stack/usage-cache.json
# Downloaded rule-set sources are pure cache — nothing here is worth keeping
# across an uninstall, and leaving them behind means the next install silently
# starts from a stale copy.
run rm -rf /var/lib/anyreality-resi-stack/rulesets

# The installer's kernel tuning changes host behaviour (congestion control,
# keepalive, buffers). Leaving it in place after an uninstall means the machine
# is still carrying settings from software that is no longer there.
step "Reverting kernel tuning"
if [[ -f /etc/sysctl.d/99-anyreality.conf ]]; then
  run rm -f /etc/sysctl.d/99-anyreality.conf
  # Reload so the running kernel stops reflecting a file that no longer exists.
  # Values already applied are not rolled back by sysctl --system; a reboot
  # returns them to distro defaults, which is why this says so out loud.
  run sysctl --system >/dev/null
  info "Removed /etc/sysctl.d/99-anyreality.conf. Values already applied stay in"
  info "effect until reboot — that is how sysctl works, not a leftover."
else
  info "No /etc/sysctl.d/99-anyreality.conf to remove"
fi

if [[ "$KEEP_SECRETS" == "0" ]]; then
  warn "Removing /etc/anyreality-resi-stack (secrets included)"
  run rm -rf /etc/anyreality-resi-stack /etc/reality-resi-stack
  run rm -rf /var/lib/anyreality-resi-stack /var/lib/reality-resi-stack
else
  info "Keeping /etc/anyreality-resi-stack (secrets retained; pass --purge-secrets to remove)"
fi

if [[ "$KEEP_BACKUPS" == "0" ]]; then
  warn "Removing /var/backups/anyreality-resi-stack"
  run rm -rf /var/backups/anyreality-resi-stack /var/backups/reality-resi-stack
else
  info "Keeping /var/backups/anyreality-resi-stack (pass --purge-backups to remove)"
fi

step "Removing the subscription service account"
# Only after the units are gone, and only if nothing else adopted the user.
if id -u anyreality-sub >/dev/null 2>&1; then
  run userdel anyreality-sub 2>/dev/null || warn "could not remove user anyreality-sub"
else
  info "Service account anyreality-sub not present"
fi

step "Removing the alternate-port NAT chain"
# Only this installer's own chain is touched. Flushing nat/PREROUTING wholesale
# would take Docker's rules — and everyone else's — with it.
if command -v iptables >/dev/null 2>&1; then
  run iptables -t nat -D PREROUTING -j ANYREALITY_ALTPORT 2>/dev/null || true
  run iptables -t nat -F ANYREALITY_ALTPORT 2>/dev/null || true
  run iptables -t nat -X ANYREALITY_ALTPORT 2>/dev/null || true
fi
if command -v ip6tables >/dev/null 2>&1; then
  run ip6tables -t nat -D PREROUTING -j ANYREALITY_ALTPORT 2>/dev/null || true
  run ip6tables -t nat -F ANYREALITY_ALTPORT 2>/dev/null || true
  run ip6tables -t nat -X ANYREALITY_ALTPORT 2>/dev/null || true
fi

step "Removing the CDN origin vhost"
for link in /etc/nginx/sites-enabled/anyreality-cdn-origin.conf \
  /etc/nginx/sites-available/anyreality-cdn-origin.conf; do
  if [[ -e "$link" || -L "$link" ]]; then
    run rm -f "$link"
  fi
done
if command -v nginx >/dev/null 2>&1 && systemctl is-active --quiet nginx 2>/dev/null; then
  if nginx -t >/dev/null 2>&1; then
    run systemctl reload nginx
  else
    warn "nginx -t failed after removing the vhost — not reloading; check /etc/nginx by hand"
  fi
fi

step "Removing UFW rules and fail2ban jail"
# SSH rules are deliberately left alone — removing them can lock you out.
run ufw delete allow "${INBOUND_PORT}/tcp" 2>/dev/null || true
run ufw delete allow "${INBOUND_PORT}/udp" 2>/dev/null || true
run ufw delete allow 80/tcp 2>/dev/null || true
# The origin-pull rules are per-CDN-range, so there is no single rule to
# delete. Enumerate by port instead.
if command -v ufw >/dev/null 2>&1; then
  while ufw status numbered 2>/dev/null | grep -qE "\[[ 0-9]+\].*(8443|2053|2083|2087|2096)/tcp"; do
    num="$(ufw status numbered 2>/dev/null |
      grep -E "\[[ 0-9]+\].*(8443|2053|2083|2087|2096)/tcp" |
      head -1 | sed 's/^\[[[:space:]]*\([0-9]*\).*/\1/')"
    [[ -n "$num" ]] || break
    run ufw --force delete "$num" || break
  done
fi
if [[ -f /etc/fail2ban/jail.d/sshd.local ]]; then
  run rm -f /etc/fail2ban/jail.d/sshd.local
fi

ok "Uninstall complete. sing-box binary (apt-managed) left in place."
info "UFW rules for SSH were left in place on purpose. Review with: ufw status numbered"
