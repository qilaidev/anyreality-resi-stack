#!/usr/bin/env bash
# singbox.sh — install sing-box from official apt source, generate keys,
# render configuration, install systemd unit, run E2E verification.

# shellcheck source=./common.sh
[[ -n "${COMMON_SH_LOADED:-}" ]] || {
  echo "singbox.sh: source common.sh first" >&2
  exit 1
}

# Pinned GPG fingerprints of the Sagernet apt repository signing key bundle.
# Verified against https://sing-box.app/gpg.key on 2026-05-17 — the bundle
# contains a primary key plus a signing subkey, both with their own fingerprint.
# We require the EXPECTED fingerprint to be present anywhere in the bundle
# (not just first), so upstream subkey rotation does not break us.
# Override with SINGBOX_APT_KEY_FPR=<fpr> if you've pinned a newer rotation.
SINGBOX_APT_KEY_FPR="${SINGBOX_APT_KEY_FPR:-2C317FBD5D886B4E89BAE8DA6D9152172A2B2F0C}"

# ── Install sing-box from official apt repo ──────────────────────────────
phase_install_singbox() {
  step "Installing sing-box from Sagernet apt repo"

  run mkdir -p /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/sagernet.asc ]]; then
    run curl -fsSL https://sing-box.app/gpg.key -o /etc/apt/keyrings/sagernet.asc
    run chmod a+r /etc/apt/keyrings/sagernet.asc
  fi

  # Verify the expected fingerprint is in the bundle.
  if [[ "$DRY_RUN" != "1" ]]; then
    local all_fprs
    all_fprs="$(gpg --show-keys --with-colons /etc/apt/keyrings/sagernet.asc 2>/dev/null |
      awk -F: '$1=="fpr" {print $10}')"
    if ! grep -qxF "$SINGBOX_APT_KEY_FPR" <<<"$all_fprs"; then
      die "Sagernet GPG fingerprint mismatch.
Expected (any of): $SINGBOX_APT_KEY_FPR
Got bundle fingerprints:
$all_fprs
Refusing to install — possible supply-chain tampering. If Sagernet has rotated keys,
re-pin via: SINGBOX_APT_KEY_FPR=<new-fpr> bash install/install.sh ..."
    fi
    ok "GPG fingerprint verified: $SINGBOX_APT_KEY_FPR present in bundle"
  fi

  write_file /etc/apt/sources.list.d/sagernet.sources 0644 <<'EOF'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
EOF

  run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  local pkg=sing-box
  if [[ -n "${SINGBOX_VERSION:-}" ]]; then
    pkg="sing-box=${SINGBOX_VERSION}"
    info "Pinning sing-box apt package version: ${SINGBOX_VERSION}"
  fi
  run env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install "$pkg"

  if [[ "$DRY_RUN" != "1" ]]; then
    sing-box version | head -1 | while read -r line; do ok "$line"; done
  fi
}

# gen_anytls_password — mint a random AnyTLS password (base64, url-safe enough
# for env/JSON). Falls back to uuidgen when openssl is unavailable.
gen_anytls_password() {
  openssl rand -base64 24 2>/dev/null || uuidgen
}

gen_secret() { openssl rand -hex 16 2>/dev/null || uuidgen; }

# ensure_hy2_cert — self-signed certificate for the Hysteria2 inbound.
#
# Hysteria2 needs TLS, and requiring a domain for it would make the UDP
# fallback path unavailable to exactly the IP-only deployments that need a
# fallback most. The alternative usually chosen — `insecure: true` on the
# client — hands the node password to anyone who can MITM the path.
#
# Neither is necessary: the client profile pins THIS certificate, so a
# self-signed cert is verified exactly as strictly as a public one, against a
# trust anchor of one. No domain, no CA, no skip-verify switch.
ensure_hy2_cert() {
  local cert="$1" key="$2" cn="$3"
  if [[ -s "$cert" && -s "$key" ]]; then
    info "Reusing existing Hysteria2 certificate at $cert"
    return 0
  fi
  mkdir -p "$(dirname "$cert")"
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "$key" -out "$cert" -days 3650 -nodes -subj "/CN=$cn" \
    -addext "subjectAltName=DNS:$cn" >/dev/null 2>&1 ||
    die "Failed to generate the Hysteria2 self-signed certificate"
  chmod 600 "$key"
  chmod 644 "$cert"
  ok "Generated a self-signed Hysteria2 certificate (pinned in the client profile)"
}

# _migrate_dir <old> <new> — move a legacy dir to its new prefix, only when the
# new destination does not yet exist (never clobber an already-migrated host).
_migrate_dir() {
  local src="$1" dst="$2"
  [[ -e "$src" ]] || return 0
  if [[ -e "$dst" ]]; then
    warn "Both $src and $dst exist — leaving $src untouched (review manually)"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  mv "$src" "$dst"
  info "moved $src -> $dst"
}

# ── Migrate legacy reality-resi-stack paths → anyreality-resi-stack ───────
# v1.x installed under the reality-resi-stack prefix. When upgrading such a
# host in place, relocate secrets/state/backups and drop the old backup unit
# so the renamed v2 layout reuses the existing UUID / Reality keys instead of
# regenerating them (which would break every already-imported client).
phase_migrate_legacy_paths() {
  local legacy=(
    /etc/reality-resi-stack
    /var/lib/reality-resi-stack
    /usr/local/lib/reality-resi-stack
    /var/backups/reality-resi-stack
    /usr/local/sbin/backup-reality-resi-stack.sh
    /etc/systemd/system/reality-resi-stack-backup.service
    /etc/systemd/system/reality-resi-stack-backup.timer
  )
  local present=0 p
  for p in "${legacy[@]}"; do
    [[ -e "$p" ]] && present=1
  done
  [[ "$present" == "1" ]] || return 0

  step "Migrating legacy reality-resi-stack layout to anyreality-resi-stack"

  if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry] would stop the legacy backup unit, remove old unit/script, and move"
    info "[dry]   /etc, /var/lib, /usr/local/lib, /var/backups dirs to the anyreality-resi-stack prefix"
    return 0
  fi

  # Retire the renamed backup unit/script (subscription and sing-box units keep
  # the same names, so they are simply overwritten by the later phases).
  for unit in reality-resi-stack-backup.timer reality-resi-stack-backup.service; do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$unit"
  done
  rm -f /usr/local/sbin/backup-reality-resi-stack.sh

  _migrate_dir /etc/reality-resi-stack /etc/anyreality-resi-stack
  _migrate_dir /var/lib/reality-resi-stack /var/lib/anyreality-resi-stack
  _migrate_dir /usr/local/lib/reality-resi-stack /usr/local/lib/anyreality-resi-stack
  _migrate_dir /var/backups/reality-resi-stack /var/backups/anyreality-resi-stack

  systemctl daemon-reload >/dev/null 2>&1 || true
  ok "Legacy layout migrated to anyreality-resi-stack (existing keys preserved)"
}

# ── Generate keys (writes secrets.env) ───────────────────────────────────
phase_generate_keys() {
  step "Generating per-server secrets"

  local secrets=/etc/anyreality-resi-stack/secrets.env

  if [[ -f "$secrets" ]]; then
    info "Secrets already exist at $secrets — reusing (will not regenerate)"
    if [[ "$DRY_RUN" == "1" ]]; then
      # Never read real secrets in dry-run, but the later phases still need
      # every template variable defined or render_template aborts. Export
      # obvious placeholders so `--dry-run` works on an already-installed host.
      UUID="00000000-0000-0000-0000-000000000000"
      REALITY_PRIVATE_KEY="<existing-private-key-unchanged>"
      REALITY_PUBLIC_KEY="<existing-public-key-unchanged>"
      SUB_TOKEN="<existing-sub-token-unchanged>"
      SHORT_ID="${SHORT_ID:-}"
      ANYTLS_PASSWORD="<existing-anytls-password-unchanged>"
      export UUID REALITY_PRIVATE_KEY REALITY_PUBLIC_KEY SUB_TOKEN SHORT_ID ANYTLS_PASSWORD
      return 0
    fi
    # shellcheck source=/dev/null
    . "$secrets"
    : "${UUID:?}" "${REALITY_PRIVATE_KEY:?}" "${REALITY_PUBLIC_KEY:?}" "${SUB_TOKEN:?}"
    SHORT_ID="${SHORT_ID:-}"
    # Backward-compat: installs predating AnyReality have no ANYTLS_PASSWORD.
    # Mint one and append so switching to --protocol anytls-reality just works,
    # without disturbing the existing UUID / Reality keypair.
    if [[ -z "${ANYTLS_PASSWORD:-}" ]]; then
      ANYTLS_PASSWORD="$(gen_anytls_password)"
      printf 'ANYTLS_PASSWORD=%s\n' "$ANYTLS_PASSWORD" >>"$secrets"
      info "Added ANYTLS_PASSWORD to existing secrets.env"
    fi
    # Same append-if-missing treatment for the paths added after the first
    # install. Regenerating any of these would invalidate every client that
    # already imported the profile, so they are only ever added, never rotated.
    _append_secret_if_missing "$secrets" HY2_PASSWORD "$(gen_anytls_password)"
    _append_secret_if_missing "$secrets" HY2_OBFS_PASSWORD "$(gen_anytls_password)"
    _append_secret_if_missing "$secrets" CDN_WS_PATH "/$(gen_secret)"
    export UUID REALITY_PRIVATE_KEY REALITY_PUBLIC_KEY SUB_TOKEN SHORT_ID ANYTLS_PASSWORD \
      HY2_PASSWORD HY2_OBFS_PASSWORD CDN_WS_PATH
    return 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry] would write $secrets with new UUID, Reality keypair, SUB_TOKEN, ANYTLS_PASSWORD, HY2_PASSWORD, HY2_OBFS_PASSWORD, CDN_WS_PATH"
    UUID="00000000-0000-0000-0000-000000000000"
    REALITY_PRIVATE_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    REALITY_PUBLIC_KEY="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    SUB_TOKEN="example-token-do-not-use"
    SHORT_ID=""
    ANYTLS_PASSWORD="example-anytls-password-do-not-use"
    HY2_PASSWORD="example-hy2-password-do-not-use"
    HY2_OBFS_PASSWORD="example-obfs-password-do-not-use"
    CDN_WS_PATH="/example-ws-path"
    export UUID REALITY_PRIVATE_KEY REALITY_PUBLIC_KEY SUB_TOKEN SHORT_ID ANYTLS_PASSWORD \
      HY2_PASSWORD HY2_OBFS_PASSWORD CDN_WS_PATH
    return 0
  fi

  UUID="$(uuidgen)"
  local kp pri pub
  kp="$(sing-box generate reality-keypair)"
  pri="$(awk '/PrivateKey/ {print $2}' <<<"$kp")"
  pub="$(awk '/PublicKey/ {print $2}' <<<"$kp")"
  [[ -n "$pri" && -n "$pub" ]] || die "Reality keypair generation failed"
  REALITY_PRIVATE_KEY="$pri"
  REALITY_PUBLIC_KEY="$pub"
  SUB_TOKEN="$(uuidgen)"
  SHORT_ID="${SHORT_ID:-$(openssl rand -hex 8 2>/dev/null || echo "")}"
  ANYTLS_PASSWORD="$(gen_anytls_password)"
  HY2_PASSWORD="$(gen_anytls_password)"
  HY2_OBFS_PASSWORD="$(gen_anytls_password)"
  # A random WS path. Not a secret in the cryptographic sense — it is in the
  # profile — but a predictable path invites anyone who guesses the origin
  # hostname to poke the relay directly.
  CDN_WS_PATH="/$(gen_secret)"

  mkdir -p "$(dirname "$secrets")"
  {
    printf 'UUID=%s\n' "$UUID"
    printf 'REALITY_PRIVATE_KEY=%s\n' "$REALITY_PRIVATE_KEY"
    printf 'REALITY_PUBLIC_KEY=%s\n' "$REALITY_PUBLIC_KEY"
    printf 'SUB_TOKEN=%s\n' "$SUB_TOKEN"
    printf 'SHORT_ID=%s\n' "$SHORT_ID"
    printf 'ANYTLS_PASSWORD=%s\n' "$ANYTLS_PASSWORD"
    printf 'HY2_PASSWORD=%s\n' "$HY2_PASSWORD"
    printf 'HY2_OBFS_PASSWORD=%s\n' "$HY2_OBFS_PASSWORD"
    printf 'CDN_WS_PATH=%s\n' "$CDN_WS_PATH"
  } >"$secrets"
  chmod 600 "$secrets"
  ok "Secrets written to $secrets (mode 600)"

  export UUID REALITY_PRIVATE_KEY REALITY_PUBLIC_KEY SUB_TOKEN SHORT_ID ANYTLS_PASSWORD \
    HY2_PASSWORD HY2_OBFS_PASSWORD CDN_WS_PATH
}

# _append_secret_if_missing <file> <name> <value> — add a key only when absent.
_append_secret_if_missing() {
  local file="$1" name="$2" value="$3"
  if grep -q "^${name}=" "$file" 2>/dev/null; then
    return 0
  fi
  printf '%s=%s\n' "$name" "$value" >>"$file"
  printf -v "$name" '%s' "$value"
  info "Added $name to existing secrets.env"
}

# ── Render configuration ─────────────────────────────────────────────────
phase_configure_singbox() {
  step "Rendering sing-box configuration"

  : "${UUID:?}" "${REALITY_PRIVATE_KEY:?}" "${SNI:?}" "${INBOUND_PORT:?}"
  : "${SHORT_ID=}"
  local protocol="${PROTOCOL:-vless-reality}"

  local conf=/etc/sing-box/conf
  run mkdir -p "$conf" /etc/sing-box/logs

  local tpl="$REPO_ROOT/templates/singbox"
  run cp "$tpl/00_log.json" "$conf/00_log.json"
  run cp "$tpl/01_outbounds.json" "$conf/01_outbounds.json"
  run cp "$tpl/03_route.json" "$conf/03_route.json"
  run cp "$tpl/05_dns.json" "$conf/05_dns.json"
  run cp "$tpl/06_ntp.json" "$conf/06_ntp.json"

  # sing-box loads every *.json under conf/. Two Reality inbounds on the same
  # port would collide, so drop every previously-rendered inbound before
  # writing the ones this run needs (idempotent protocol/path switch).
  run rm -f "$conf/11_xtls-reality_inbounds.json" "$conf/11_anytls-reality_inbounds.json" \
    "$conf/12_hysteria2_inbounds.json" "$conf/13_vless-ws_inbounds.json"

  if [[ "$protocol" == "anytls-reality" ]]; then
    : "${ANYTLS_PASSWORD:?}"
    render_template \
      "$tpl/11_anytls-reality_inbounds.json.tmpl" \
      "$conf/11_anytls-reality_inbounds.json" \
      0644
    info "Inbound protocol: AnyTLS + Reality (sing-box clients only)"
  else
    render_template \
      "$tpl/11_xtls-reality_inbounds.json.tmpl" \
      "$conf/11_xtls-reality_inbounds.json" \
      0644
    info "Inbound protocol: VLESS + Reality + xtls-rprx-vision"
  fi

  # ── Path 2: Hysteria2 over UDP ────────────────────────────────────────
  # A second protocol on a second transport, not redundancy. When TCP is being
  # actively interfered with — SYN accepted, ClientHello dropped — a UDP-based
  # protocol often still passes. The converse also happens (whole UDP ranges
  # are dropped on some mobile paths), which is why neither one alone is
  # enough and why the client races both.
  if [[ "${WITH_HYSTERIA2:-0}" == "1" ]]; then
    : "${HY2_PASSWORD:?}" "${HY2_OBFS_PASSWORD:?}"
    HY2_PORT="${HY2_PORT:-$INBOUND_PORT}"
    HY2_SNI="${HY2_SNI:-$SNI}"
    HY2_CERT_PATH=/etc/anyreality-resi-stack/hy2-cert.pem
    HY2_KEY_PATH=/etc/anyreality-resi-stack/hy2-key.pem
    export HY2_PORT HY2_SNI HY2_CERT_PATH HY2_KEY_PATH
    if [[ "$DRY_RUN" == "1" ]]; then
      info "[dry] would generate a self-signed Hysteria2 certificate at $HY2_CERT_PATH"
    else
      ensure_hy2_cert "$HY2_CERT_PATH" "$HY2_KEY_PATH" "$HY2_SNI"
    fi
    render_template \
      "$tpl/12_hysteria2_inbounds.json.tmpl" \
      "$conf/12_hysteria2_inbounds.json" \
      0644
    info "Inbound: Hysteria2 on udp/${HY2_PORT} (salamander obfs)"
  fi

  # ── Path 3: VLESS + WebSocket, fronted by a CDN ───────────────────────
  # Loopback only: nginx terminates TLS on the origin-pull port and forwards
  # here through the ping injector. This is the path that still works when the
  # server's own IP is blackholed, which is the normal state of affairs for
  # some carriers.
  if [[ -n "${CDN_DOMAIN:-}" ]]; then
    : "${CDN_WS_PATH:?}"
    render_template \
      "$tpl/13_vless-ws_inbounds.json.tmpl" \
      "$conf/13_vless-ws_inbounds.json" \
      0644
    info "Inbound: VLESS + WS on 127.0.0.1:18443 (CDN relay for ${CDN_DOMAIN})"
  fi

  # IPv6 dead-route guard. On hosts with NO public IPv6 default route, any
  # client-passed IPv6 literal target is unreachable and otherwise spams
  # "network is unreachable" while connections stall. Fast-reject those.
  # Hosts that DO have an IPv6 default route are left untouched so real IPv6
  # egress keeps working — the rule is opt-in by environment, never forced.
  if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry] would add IPv6 fast-reject rule when no IPv6 default route exists"
  elif ip -6 route show default 2>/dev/null | grep -q .; then
    info "IPv6 default route present — leaving IPv6 egress enabled"
  else
    info "No IPv6 default route — adding fast-reject rule for IPv6 targets"
    python3 - "$conf/03_route.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    cfg = json.load(handle)

rules = cfg.setdefault("route", {}).setdefault("rules", [])
guard = {"action": "reject", "ip_version": 6}
if guard not in rules:
    # Keep the sniff rule first; insert the guard right after it.
    insert_at = 0
    for i, rule in enumerate(rules):
        if rule.get("action") == "sniff":
            insert_at = i + 1
            break
    rules.insert(insert_at, guard)

with open(path, "w", encoding="utf-8") as handle:
    json.dump(cfg, handle, indent=2)
    handle.write("\n")
PY
  fi

  if [[ "$DRY_RUN" != "1" ]]; then
    sing-box check -C "$conf" || die "sing-box config check failed"
    ok "Config validates"
  fi
}

# ── Log rotation ─────────────────────────────────────────────────────────
# 00_log.json writes to /etc/sing-box/logs/box.log with no size bound. At
# level=error that file is normally tiny, but a persistent failure (dead
# upstream DNS, a probing flood, a bad config after an upgrade) turns it into
# the fastest way to fill a small VPS disk — at which point sing-box, journald
# and the backup timer all fail together. Cap it.
#
# copytruncate rather than a postrotate HUP: sing-box holds the log fd open and
# `kill -HUP` triggers a full config reload, which is a heavier and riskier
# operation than truncating a file we already keep small.
phase_logrotate() {
  step "Installing logrotate policy for sing-box"
  write_file /etc/logrotate.d/sing-box 0644 <<'EOF'
/etc/sing-box/logs/*.log {
  daily
  rotate 7
  maxsize 20M
  missingok
  notifempty
  compress
  delaycompress
  copytruncate
  su root root
  create 0640 root root
}
EOF
  if [[ "$DRY_RUN" != "1" ]]; then
    if logrotate -d /etc/logrotate.d/sing-box >/dev/null 2>&1; then
      ok "logrotate policy validates"
    else
      warn "logrotate -d rejected /etc/logrotate.d/sing-box — review it manually"
    fi
  fi
}

# ── systemd unit ─────────────────────────────────────────────────────────
phase_singbox_service() {
  step "Installing sing-box systemd unit"
  run cp "$REPO_ROOT/templates/systemd/sing-box.service" \
    /etc/systemd/system/sing-box.service
  svc_enable_now sing-box
  ok "sing-box service enabled"
}

# ── Optional: Selective Cloudflare WARP WireGuard egress ─────────────────
phase_warp_egress() {
  step "Configuring selective Cloudflare WARP WireGuard egress (--with-warp)"
  local creds="${WARP_CONFIG:-/etc/anyreality-resi-stack/warp-credentials.json}"
  if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry] would register/load WARP credentials at $creds, write 02_warp_endpoints.json, update 03_route.json + 05_dns.json, and arm warp-watchdog.timer"
    return 0
  fi

  if [[ ! -s "$creds" ]]; then
    info "Registering a new Cloudflare WARP device keypair -> $creds"
    python3 "$LIB_DIR/warp_egress.py" register --out "$creds" ||
      die "Cloudflare WARP registration failed (you can also pass a pre-registered file via --warp-config)"
  else
    info "Reusing existing WARP credentials at $creds"
  fi

  python3 "$LIB_DIR/warp_egress.py" enable \
    --credentials "$creds" \
    --conf-dir /etc/sing-box/conf ||
    die "Failed to enable selective WARP egress in /etc/sing-box/conf"

  run cp "$REPO_ROOT/templates/systemd/warp-watchdog.service" \
    /etc/systemd/system/warp-watchdog.service
  run cp "$REPO_ROOT/templates/systemd/warp-watchdog.timer" \
    /etc/systemd/system/warp-watchdog.timer
  run systemctl daemon-reload
  run systemctl enable --now warp-watchdog.timer
  ok "Selective WARP egress active + warp-watchdog.timer armed (every 2m)"
}

# ── End-to-end verification ──────────────────────────────────────────────
phase_verify() {
  step "End-to-end verification"

  if [[ "$DRY_RUN" == "1" ]]; then
    info "[dry] skipping verify — nothing was actually installed"
    return 0
  fi

  local fails=0

  if svc_is_active sing-box; then
    ok "sing-box is active"
  else
    fail "sing-box not active"
    fails=$((fails + 1))
  fi

  if ss -tlnp 2>/dev/null | grep -q ":${INBOUND_PORT} "; then
    ok "Listening on tcp/${INBOUND_PORT}"
  else
    fail "Not listening on tcp/${INBOUND_PORT}"
    fails=$((fails + 1))
  fi

  if sing-box check -C /etc/sing-box/conf >/dev/null 2>&1; then
    ok "sing-box check OK"
  else
    fail "sing-box check failed"
    fails=$((fails + 1))
  fi

  # A UDP listener is easy to configure and easy to leave unreachable: UFW
  # rules are per-protocol, and `ufw allow 443` opens TCP only. The inbound
  # then looks perfectly healthy from the server while every client times out.
  if [[ "${WITH_HYSTERIA2:-0}" == "1" ]]; then
    local hy2_port="${HY2_PORT:-$INBOUND_PORT}"
    if ss -ulnp 2>/dev/null | grep -q ":${hy2_port} "; then
      ok "Listening on udp/${hy2_port} (Hysteria2)"
    else
      fail "Not listening on udp/${hy2_port} — Hysteria2 path is dead"
      fails=$((fails + 1))
    fi
    if ufw status 2>/dev/null | grep -qE "^${hy2_port}/udp[[:space:]]+ALLOW"; then
      ok "UFW allows udp/${hy2_port}"
    else
      fail "UFW does not allow udp/${hy2_port} — clients will time out with the port open locally"
      fails=$((fails + 1))
    fi
  fi

  if [[ -n "${CDN_DOMAIN:-}" ]]; then
    if ss -tlnp 2>/dev/null | grep -q "127.0.0.1:18443"; then
      ok "VLESS+WS inbound listening on 127.0.0.1:18443"
    else
      fail "VLESS+WS inbound not listening — CDN relay path is dead"
      fails=$((fails + 1))
    fi
    if svc_is_active ws-ping-inject; then
      ok "ws-ping-inject active"
    else
      fail "ws-ping-inject not active — the CDN will close idle tunnels after ~100s"
      fails=$((fails + 1))
    fi
  fi

  if [[ "${WITH_WARP:-0}" == "1" ]]; then
    if [[ -f /etc/sing-box/conf/02_warp_endpoints.json ]]; then
      ok "02_warp_endpoints.json present"
    else
      fail "02_warp_endpoints.json missing despite --with-warp"
      fails=$((fails + 1))
    fi
    if ss -tlnp 2>/dev/null | grep -q "127.0.0.1:10809"; then
      ok "WARP probe inbound listening on 127.0.0.1:10809"
    else
      fail "WARP probe inbound not listening on 127.0.0.1:10809"
      fails=$((fails + 1))
    fi
    if python3 "$LIB_DIR/warp_egress.py" audit --conf-dir /etc/sing-box/conf >/dev/null 2>&1; then
      ok "WARP routing invariants (C9) verified"
    else
      fail "WARP routing invariants (C9) failed"
      fails=$((fails + 1))
    fi
  fi

  # TLS handshake self-test — confirms Reality is fronting the configured SNI.
  if command -v openssl >/dev/null 2>&1; then
    if echo | timeout 5 openssl s_client \
      -connect "127.0.0.1:${INBOUND_PORT}" \
      -servername "${SNI}" -verify_quiet 2>/dev/null |
      grep -q "subject="; then
      ok "TLS handshake to 127.0.0.1:${INBOUND_PORT} produced a certificate (Reality fronting works)"
    else
      warn "TLS self-handshake produced no cert — Reality may still be OK; verify from a real client"
    fi
  fi

  if [[ "${WITH_SUBSCRIPTION:-0}" == "1" || "${WITH_AGGREGATOR:-0}" == "1" ]]; then
    # With TLS on, the certificate is issued for a hostname while we probe the
    # loopback address, so -k is expected here — this checks liveness, not trust.
    local health_url="http://127.0.0.1/healthz" curl_opts=(-fsS --max-time 5)
    if [[ -n "${SUB_TLS_CERT:-}" ]]; then
      health_url="https://127.0.0.1/healthz"
      curl_opts+=(-k)
    fi
    if curl "${curl_opts[@]}" "$health_url" >/dev/null 2>&1; then
      ok "Subscription /healthz responds"
    else
      fail "Subscription /healthz does not respond ($health_url)"
      fails=$((fails + 1))
    fi
  fi

  if ((fails > 0)); then
    die "Verification: $fails check(s) failed"
  fi
  ok "All verification checks passed"
}
