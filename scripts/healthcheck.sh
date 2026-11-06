#!/usr/bin/env bash
# healthcheck.sh — read-only production health check for an installed
# anyreality-resi-stack node. Changes nothing; safe to run at any time.
#
# Installed by the installer as:
#   /usr/local/sbin/anyreality-resi-stack-healthcheck
#
# Usage:
#   anyreality-resi-stack-healthcheck           # human-readable report
#   anyreality-resi-stack-healthcheck --quiet   # print only problems (cron)
#
# Exit codes:
#   0  everything healthy (warnings may still be printed)
#   1  at least one FAIL — the node is degraded or down
#
# Cron alerting (mails you only when something is wrong, because cron mails on
# any output and --quiet stays silent while healthy):
#   */10 * * * * /usr/local/sbin/anyreality-resi-stack-healthcheck --quiet

set -Eeuo pipefail

# Any unexpected early exit is reported. Without this the script could stop
# halfway through and simply return, which reads exactly like "nothing to say".
reached_summary=0
report_early_exit() {
  local status=$?
  [[ "$reached_summary" == "1" ]] && return 0
  printf '\033[1;31m[FAIL]\033[0m healthcheck exited early (status %s) — the checks after that point did NOT run\n' \
    "$status" >&2
  exit 1
}
trap report_early_exit EXIT

CONF_DIR=/etc/sing-box/conf
LOG_DIR=/etc/sing-box/logs
ETC_DIR=/etc/anyreality-resi-stack
BACKUP_DIR=/var/backups/anyreality-resi-stack
HOOK_DIR=/etc/anyreality-resi-stack/backup-hooks.d
BACKUP_MAX_AGE_HOURS=48
DISK_WARN_PCT=80
DISK_FAIL_PCT=90
LOG_WARN_MB=50
# Host that serves Cloudflare's Turnstile/challenge widget. It has had AAAA
# records only (no A) for a long time — verified against 1.1.1.1 / 8.8.8.8 /
# 9.9.9.9 — which is why IPv6 egress is not optional if you want CAPTCHAs to
# be solvable. See the IPv6 check near the end of this script.
CF_CHALLENGE_HOST=brunhild.challenges.cloudflare.com

QUIET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -q | --quiet)
      QUIET=1
      shift
      ;;
    -h | --help)
      sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

C_RESET=$'\033[0m'
C_GREEN=$'\033[1;32m'
C_YELLOW=$'\033[1;33m'
C_RED=$'\033[1;31m'

fails=0
warns=0

pass() {
  ((QUIET == 1)) || printf "%s[ OK ]%s %s\n" "$C_GREEN" "$C_RESET" "$*"
}
warn() {
  warns=$((warns + 1))
  printf "%s[WARN]%s %s\n" "$C_YELLOW" "$C_RESET" "$*" >&2
}
fail() {
  fails=$((fails + 1))
  printf "%s[FAIL]%s %s\n" "$C_RED" "$C_RESET" "$*" >&2
}

# ── sing-box ─────────────────────────────────────────────────────────────
if systemctl is-active --quiet sing-box; then
  pass "sing-box service is active"
else
  fail "sing-box service is NOT active — run: systemctl status sing-box"
fi

restarts="$(systemctl show sing-box -p NRestarts --value 2>/dev/null || echo 0)"
if [[ "$restarts" =~ ^[0-9]+$ ]] && ((restarts >= 5)); then
  warn "sing-box has restarted $restarts times — check journalctl -u sing-box for a crash loop"
else
  pass "sing-box restart count: ${restarts:-0}"
fi

if [[ -d "$CONF_DIR" ]] && command -v sing-box >/dev/null 2>&1; then
  if sing-box check -C "$CONF_DIR" >/dev/null 2>&1; then
    pass "sing-box config validates"
  else
    fail "sing-box config check FAILED — a restart would not come back up"
  fi
else
  fail "sing-box config directory $CONF_DIR missing or sing-box not installed"
fi

# Inbound port comes from the rendered config, not a hard-coded 443.
inbound_port="$(
  grep -ho '"listen_port"[[:space:]]*:[[:space:]]*[0-9]\+' "$CONF_DIR"/11_*.json 2>/dev/null |
    grep -o '[0-9]\+' | head -1
)"
inbound_port="${inbound_port:-443}"
if ss -tlnH 2>/dev/null | grep -qE "[:.]${inbound_port}[[:space:]]"; then
  pass "listening on tcp/${inbound_port}"
else
  fail "nothing is listening on tcp/${inbound_port} — clients cannot connect"
fi

# ── Subscription service (only if one is installed) ──────────────────────
sub_unit=""
for candidate in subscription-leaf subscription-aggregator; do
  if systemctl list-unit-files "${candidate}.service" >/dev/null 2>&1 &&
    [[ -f "/etc/systemd/system/${candidate}.service" ]]; then
    sub_unit="$candidate"
  fi
done

if [[ -n "$sub_unit" ]]; then
  if systemctl is-active --quiet "$sub_unit"; then
    pass "$sub_unit is active"
  else
    fail "$sub_unit is NOT active — subscription URLs are down"
  fi

  sub_port="$(awk -F= '/^PORT=/ {print $2}' "$ETC_DIR/${sub_unit}.env" 2>/dev/null | tail -1)"
  sub_port="${sub_port:-80}"
  # With TLS enabled the certificate is for a hostname, not 127.0.0.1, so -k is
  # correct here: this probes liveness, not certificate trust.
  sub_scheme="http"
  curl_opts=(-fsS --max-time 5)
  if grep -q '^TLS_CERT_FILE=.' "$ETC_DIR/${sub_unit}.env" 2>/dev/null; then
    sub_scheme="https"
    curl_opts+=(-k)
  fi
  if curl "${curl_opts[@]}" "${sub_scheme}://127.0.0.1:${sub_port}/healthz" >/dev/null 2>&1; then
    pass "subscription /healthz responds on ${sub_scheme}://:${sub_port}"
  else
    fail "subscription /healthz does not respond on ${sub_scheme}://:${sub_port}"
  fi

  # An expired certificate is a silent outage: clients refuse the subscription
  # while /healthz over -k keeps reporting green.
  if [[ "$sub_scheme" == "https" ]]; then
    cert_file="$(awk -F= '/^TLS_CERT_FILE=/ {print $2}' "$ETC_DIR/${sub_unit}.env" | tail -1)"
    if [[ -f "$cert_file" ]] && command -v openssl >/dev/null 2>&1; then
      if openssl x509 -in "$cert_file" -noout -checkend 604800 >/dev/null 2>&1; then
        pass "TLS certificate valid for at least 7 more days"
      else
        fail "TLS certificate expires within 7 days (or is unreadable): $cert_file"
      fi
    fi
  fi

  file_dir="$(awk -F= '/^FILE_DIR=/ {print $2}' "$ETC_DIR/${sub_unit}.env" 2>/dev/null | tail -1)"
  target="$(awk -F= '/^DEFAULT_TARGET=/ {print $2}' "$ETC_DIR/${sub_unit}.env" 2>/dev/null | tail -1)"
  file_dir="${file_dir:-$ETC_DIR/files}"
  if [[ -n "$target" && -s "$file_dir/$target" ]]; then
    pass "profile file present: $file_dir/$target"
  else
    fail "profile file missing or empty: ${file_dir}/${target:-<unset>} — subscriptions return 404"
  fi
fi

# ── Backups ──────────────────────────────────────────────────────────────
if systemctl is-enabled --quiet anyreality-resi-stack-backup.timer 2>/dev/null; then
  pass "backup timer is enabled"
  if [[ "$(systemctl is-failed anyreality-resi-stack-backup.service 2>/dev/null)" == "failed" ]]; then
    fail "last backup run FAILED — journalctl -u anyreality-resi-stack-backup.service"
  fi
  newest="$(find "$BACKUP_DIR" -name 'anyreality-resi-stack-*.tar.gz' -type f -print 2>/dev/null |
    sort | tail -1 || true)"
  if [[ -z "$newest" ]]; then
    # A freshly installed host has no archive yet because the daily timer has
    # simply not fired. Failing there would make the very first health check
    # after every install report a problem — and the documented cron setup
    # mails on any failure, so it would page the operator for nothing. Only a
    # backup unit that HAS run and still left nothing behind is a real fault.
    if [[ -z "$(systemctl show -p ExecMainStartTimestamp --value \
      anyreality-resi-stack-backup.service 2>/dev/null)" ]]; then
      warn "no backup archive yet — the daily timer has not fired since install; re-check tomorrow, or force one now with: systemctl start anyreality-resi-stack-backup.service"
    else
      fail "no backup archive found in $BACKUP_DIR — the backup unit has run and produced nothing, so there is nothing to roll back to"
    fi
  else
    age_h=$((($(date +%s) - $(stat -c %Y "$newest" 2>/dev/null || echo 0)) / 3600))
    if ((age_h > BACKUP_MAX_AGE_HOURS)); then
      warn "newest backup is ${age_h}h old (> ${BACKUP_MAX_AGE_HOURS}h): $newest"
    else
      pass "newest backup is ${age_h}h old: $(basename "$newest")"
    fi
  fi

  # Local-only backups do not survive losing the VPS.
  if find "$HOOK_DIR" -maxdepth 1 -type f -perm -u+x 2>/dev/null | grep -q .; then
    pass "off-box backup hook configured"
  else
    warn "no off-box backup hook in $HOOK_DIR — backups die with the host (see OPERATIONS.md)"
  fi
else
  warn "backup timer is not enabled — no rollback point is being produced"
fi

# ── Disk, logs, clock, firewall, secrets ─────────────────────────────────
disk_pct="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
if [[ "$disk_pct" =~ ^[0-9]+$ ]]; then
  if ((disk_pct >= DISK_FAIL_PCT)); then
    fail "root filesystem is ${disk_pct}% full — sing-box, journald and backups will start failing"
  elif ((disk_pct >= DISK_WARN_PCT)); then
    warn "root filesystem is ${disk_pct}% full"
  else
    pass "root filesystem ${disk_pct}% used"
  fi
fi

if [[ -f "$LOG_DIR/box.log" ]]; then
  log_mb=$(($(stat -c %s "$LOG_DIR/box.log" 2>/dev/null || echo 0) / 1024 / 1024))
  if ((log_mb > LOG_WARN_MB)); then
    warn "box.log is ${log_mb} MiB — check /etc/logrotate.d/sing-box and the error stream"
  else
    pass "box.log size ${log_mb} MiB"
  fi
fi

# Reality rejects handshakes whose clock is too far off, so a drifting clock
# looks exactly like "the protocol is blocked".
ntp_sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "")"
if [[ "$ntp_sync" == "yes" ]]; then
  pass "clock is NTP-synchronised"
else
  warn "clock is NOT NTP-synchronised — Reality handshakes may fail (systemctl status chrony)"
fi

if command -v ufw >/dev/null 2>&1; then
  if ufw status 2>/dev/null | head -1 | grep -q "active"; then
    pass "UFW is active"
  else
    warn "UFW is not active"
  fi
fi

if [[ -f "$ETC_DIR/secrets.env" ]]; then
  mode="$(stat -c %a "$ETC_DIR/secrets.env" 2>/dev/null || echo "")"
  if [[ "$mode" == "600" ]]; then
    pass "secrets.env permissions are 600"
  else
    fail "secrets.env is mode ${mode:-unknown}, expected 600 — run: chmod 600 $ETC_DIR/secrets.env"
  fi
fi

# Cloudflare's challenge widget loads from an AAAA-only host. A node with no
# usable IPv6 egress cannot fetch it, and the user-visible symptom is a
# verification page that spins forever — while the only trace on the server is
# a single "empty result" line in the error log. That is very hard to connect
# back to IPv6, so probe it explicitly and name the root cause.
#
# This matters most for exactly this project's audience: people routing
# ChatGPT/Claude/banking through the node are the ones who hit CAPTCHAs.
if [[ -f "$CONF_DIR/02_warp_endpoints.json" ]]; then
  pass "Selective WARP egress configured (challenges.cloudflare.com routed via warp-ep IPv6)"
elif [[ -n "$(command -v ip)" ]]; then
  v6_global="$(ip -6 addr show scope global 2>/dev/null | grep -c 'inet6' || true)"
  if [[ "${v6_global:-0}" -eq 0 ]]; then
    warn "no global IPv6 address — Cloudflare's challenge widget (${CF_CHALLENGE_HOST}) is AAAA-only, so CAPTCHA pages will spin forever. Fix: enable IPv6 on this VPS or pass --with-warp to route challenges over WARP IPv6. See docs/en/TROUBLESHOOTING.md, section 'Cloudflare CAPTCHA spins forever'"
  else
    code="$(curl -6 -s -o /dev/null -w '%{http_code}' --max-time 8 \
      "https://${CF_CHALLENGE_HOST}/" 2>/dev/null || echo "000")"
    if [[ "$code" != "000" ]]; then
      pass "IPv6 egress works — Cloudflare challenge widget is reachable"
    else
      warn "have IPv6 address but cannot reach ${CF_CHALLENGE_HOST} over IPv6 — CAPTCHA pages will spin forever. Check IPv6 routing/firewall (ip -6 route, ufw) or enable --with-warp"
    fi
  fi
fi

# ── Multi-path components ────────────────────────────────────────────────
# Every process on the data path gets a check here. That is a rule learned the
# hard way: the WebSocket ping injector sat on the CDN data path for weeks
# without appearing in any inventory or health check, and during an outage it
# was invisible — nobody looked at a component nobody knew existed.

LIB_DIR=/usr/local/lib/anyreality-resi-stack

if [[ -f "$CONF_DIR/12_hysteria2_inbounds.json" ]]; then
  hy2_port="$(grep -ho '"listen_port"[[:space:]]*:[[:space:]]*[0-9]\+' \
    "$CONF_DIR/12_hysteria2_inbounds.json" 2>/dev/null | grep -o '[0-9]\+' | head -1 || true)"
  hy2_port="${hy2_port:-443}"
  if ss -ulnH 2>/dev/null | grep -q ":${hy2_port} "; then
    pass "Hysteria2 listening on udp/${hy2_port}"
  else
    fail "Hysteria2 configured but nothing is listening on udp/${hy2_port}"
  fi
  # UFW rules are per-protocol: `ufw allow 443` opens TCP only, and the UDP
  # inbound then looks perfectly healthy while being unreachable from every
  # client. Check the protocol explicitly.
  if ufw status 2>/dev/null | grep -qE "^${hy2_port}/udp[[:space:]]+ALLOW"; then
    pass "UFW allows udp/${hy2_port}"
  else
    fail "UFW has no udp/${hy2_port} rule — the Hysteria2 path is unreachable from outside"
  fi
fi

if [[ -f "$CONF_DIR/13_vless-ws_inbounds.json" ]]; then
  if ss -tlnH 2>/dev/null | grep -q "127.0.0.1:18443"; then
    pass "CDN relay inbound listening on 127.0.0.1:18443"
  else
    fail "CDN relay inbound not listening on 127.0.0.1:18443"
  fi
  if systemctl is-active --quiet ws-ping-inject 2>/dev/null; then
    pass "ws-ping-inject active (keeps CDN tunnels past the ~100s idle timeout)"
  else
    fail "ws-ping-inject is down — CDN tunnels will die at ~2m05s and users will call it 'random disconnects'"
  fi
  ws_path="$(grep -ho '"path"[[:space:]]*:[[:space:]]*"[^"]*"' \
    "$CONF_DIR/13_vless-ws_inbounds.json" 2>/dev/null | sed 's/.*"\(\/[^"]*\)"/\1/' | head -1 || true)"
  # `nginx -T` prints the RUNNING configuration. `nginx -t` only says the files
  # on disk parse, which stays true after a sites-enabled symlink has been
  # replaced by a stale regular file.
  if [[ -n "$ws_path" ]]; then
    if nginx -T 2>/dev/null | grep -q -- "$ws_path"; then
      pass "nginx's running config serves the relay path"
    else
      fail "the relay path is missing from nginx's RUNNING config (nginx -T) — check sites-enabled/"
    fi
  fi
fi

if [[ -f /etc/anyreality-resi-stack/altport.env ]] && command -v iptables >/dev/null 2>&1; then
  altport_rules="$(iptables -t nat -S ANYREALITY_ALTPORT 2>/dev/null | grep -c -- '-A' || true)"
  if [[ "${altport_rules:-0}" -gt 0 ]]; then
    pass "$altport_rules alternate-port NAT redirect(s) active"
    info_note="alternate ports never appear in 'ss -tlnp' — that is expected, not a fault"
    ((QUIET == 1)) || printf "     %s\n" "$info_note"
  else
    fail "altport.env exists but no NAT redirects are installed — the alternate ports are dead (systemctl status altport-redirect)"
  fi
fi

# ── Selective WARP egress (C9) ───────────────────────────────────────────
if [[ -f "$CONF_DIR/02_warp_endpoints.json" ]]; then
  if ss -tlnH 2>/dev/null | grep -q "127.0.0.1:10809"; then
    pass "WARP probe inbound listening on 127.0.0.1:10809"
  else
    fail "02_warp_endpoints.json present but 127.0.0.1:10809 is not listening"
  fi
  if [[ -x "$LIB_DIR/warp_egress.py" ]]; then
    if warp_audit="$(python3 "$LIB_DIR/warp_egress.py" audit --conf-dir "$CONF_DIR" 2>&1)"; then
      pass "WARP routing invariants (C9) hold"
    else
      fail "WARP routing invariant violation: ${warp_audit//$'\n'/; }"
    fi
  fi
  if systemctl is-enabled --quiet warp-watchdog.timer 2>/dev/null; then
    pass "warp-watchdog.timer is enabled"
  else
    warn "warp-watchdog.timer is not enabled — a dead WARP endpoint will not auto-degrade to direct"
  fi
  if [[ -f /run/anyreality-warp-watchdog/state.json ]]; then
    if grep -q '"degraded":[[:space:]]*true' /run/anyreality-warp-watchdog/state.json 2>/dev/null; then
      warn "WARP watchdog has degraded WARP rules to direct (tunnel unreachable; probing for recovery)"
    else
      pass "WARP watchdog state: active (warp-ep)"
    fi
  fi
fi

# ── Published profile ────────────────────────────────────────────────────
if [[ -f "$ETC_DIR/files/profile.json" ]]; then
  if [[ -x "$LIB_DIR/check_profile.py" ]]; then
    check_args=("$ETC_DIR/files/profile.json")
    [[ -f "$ETC_DIR/files/profile.yaml" ]] && check_args+=("$ETC_DIR/files/profile.yaml")
    [[ -f "$ETC_DIR/files/profile.txt" ]] && check_args+=("$ETC_DIR/files/profile.txt")
    if profile_problems="$(python3 "$LIB_DIR/check_profile.py" "${check_args[@]}" 2>&1)"; then
      pass "Published profile satisfies the structural invariants"
    else
      fail "Published profile violates an invariant: ${profile_problems//$'\n'/; }"
    fi
  fi
  # C3 drift check: ensure the server's live REALITY SNI matches what the
  # published profile tells clients to send (only on single-node leaf hosts
  # where the local inbound IS the profile's primary node).
  if [[ ! -f /etc/systemd/system/subscription-aggregator.service ]] &&
    ls "$CONF_DIR"/11_*.json >/dev/null 2>&1; then
    if drift_msg="$(
      python3 - "$CONF_DIR" "$ETC_DIR/files/profile.json" <<'PY'
import glob, json, sys
conf_dir, prof_path = sys.argv[1], sys.argv[2]
inb_files = sorted(glob.glob(f"{conf_dir}/11_*.json"))
if not inb_files:
    sys.exit(0)
inb = json.load(open(inb_files[0], encoding="utf-8"))["inbounds"][0]
prof = json.load(open(prof_path, encoding="utf-8"))
srv_sni = inb.get("tls", {}).get("server_name")
srv_port = inb.get("listen_port")
reality_nodes = [
    o for o in prof.get("outbounds", [])
    if (o.get("tls") or {}).get("reality", {}).get("enabled")
]
if reality_nodes:
    cli_sni = reality_nodes[0].get("tls", {}).get("server_name")
    cli_ports = {n.get("server_port") for n in reality_nodes}
    if srv_sni and cli_sni and srv_sni != cli_sni:
        print(f"server SNI={srv_sni!r} != profile SNI={cli_sni!r}")
        sys.exit(1)
    if srv_port and srv_port not in cli_ports:
        print(f"server listen_port={srv_port} not in profile ports {sorted(cli_ports)}")
        sys.exit(1)
PY
    )"; then
      pass "Server inbound and published profile agree on SNI & port (C3)"
    else
      fail "Server inbound vs published profile drift (C3): $drift_msg — run: /usr/local/lib/anyreality-resi-stack/rebuild-profiles.sh"
    fi
  fi
  # A rule-set frozen months ago routes new domestic CDNs abroad, and every
  # check still passes because the FILES look fine. Age is the only signal.
  newest_ruleset="$(find /var/lib/anyreality-resi-stack/rulesets -name '*.json' -mtime -30 2>/dev/null | head -1 || true)"
  if [[ -d /var/lib/anyreality-resi-stack/rulesets && -z "$newest_ruleset" ]]; then
    warn "no rule-set source refreshed in 30 days — check: systemctl status refresh-rulesets.timer"
  fi
  if systemctl is-enabled --quiet refresh-rulesets.timer 2>/dev/null; then
    pass "Weekly rule-set refresh timer enabled"
  else
    warn "refresh-rulesets.timer is not enabled — routing rules will go stale"
  fi
fi

# ── Kernel tuning ────────────────────────────────────────────────────────
# Verifies EFFECTIVE values. /etc/sysctl.d/ is read in filename order and later
# files silently override earlier ones, so a key can be set in the file you
# edited and still not be in effect.
if [[ -x "$LIB_DIR/check_sysctl.py" ]]; then
  if sysctl_problems="$(python3 "$LIB_DIR/check_sysctl.py" 2>&1)"; then
    pass "Kernel network tuning is in effect"
  else
    warn "kernel tuning drift: ${sysctl_problems//$'\n'/; }"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────────
# Reaching this line is itself part of the result: an early exit under
# `set -e` used to skip every remaining check silently, so the absence of a
# verdict has to be loud.
reached_summary=1
if ((fails > 0)); then
  printf "%s%s check(s) FAILED, %s warning(s).%s\n" "$C_RED" "$fails" "$warns" "$C_RESET" >&2
  exit 1
fi
if ((warns > 0)); then
  ((QUIET == 1)) || printf "%sHealthy with %s warning(s).%s\n" "$C_YELLOW" "$warns" "$C_RESET"
  exit 0
fi
((QUIET == 1)) || printf "%sAll checks passed.%s\n" "$C_GREEN" "$C_RESET"
