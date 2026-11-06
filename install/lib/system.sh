#!/usr/bin/env bash
# system.sh — OS preflight, base packages, network tuning, firewall, fail2ban.
# Idempotent. Source this file; do not execute directly.

# shellcheck source=./common.sh
[[ -n "${COMMON_SH_LOADED:-}" ]] || {
  echo "system.sh: source common.sh first" >&2
  exit 1
}

# ── Preflight ────────────────────────────────────────────────────────────
phase_preflight() {
  step "Preflight"

  require_root

  if [[ ! -r /etc/os-release ]]; then
    die "Unsupported OS: /etc/os-release missing"
  fi
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${ID:-}" in
    ubuntu | debian) ok "OS: ${PRETTY_NAME:-$ID}" ;;
    *) die "Unsupported OS (${ID:-?}). Supported: Ubuntu 22.04+, Debian 12+." ;;
  esac

  if ! command -v curl >/dev/null 2>&1; then
    warn "curl missing — will install"
  fi

  if [[ -n "${INBOUND_PORT:-}" ]] && port_in_use "$INBOUND_PORT"; then
    if ! ss -tlnp 2>/dev/null | awk -v p=":$INBOUND_PORT" '$0~p' | grep -q sing-box; then
      die "Port $INBOUND_PORT in use by something other than sing-box. Free it first."
    fi
    warn "Port $INBOUND_PORT already held by sing-box (will be reconfigured in place)"
  fi

  # Detect a prior MANUAL sing-box install. apt installing a second copy
  # creates a conflicting binary + systemd unit + config dir that will
  # silently break on next reboot. Refuse with a clear message.
  if [[ -x /usr/local/bin/sing-box && ! -e /usr/bin/sing-box ]]; then
    die "Detected an existing manually-installed sing-box at /usr/local/bin/sing-box.
This installer uses the official Sagernet apt repo and would create a second,
conflicting binary at /usr/bin/sing-box plus its own sing-box.service unit.
Refusing to proceed.

Options:
  1. Remove the manual install first:
       systemctl stop <your-custom-sing-box-unit>.service
       rm /usr/local/bin/sing-box
     Then re-run this installer.

  2. Keep your existing manual install and ignore this installer for sing-box.
     You can still use this repo's templates and subscription server manually."
  fi

  # Detect a foreign systemd unit managing sing-box under a different name.
  #
  # Two units are NOT foreign and must never trip this check:
  #   sing-box.service   — the unit this installer manages.
  #   sing-box@.service  — a systemd *template*, shipped by the official apt
  #                        package itself. A template manages nothing until it
  #                        is instantiated, and it is present on every host that
  #                        has sing-box installed — so flagging it made the
  #                        second run of an installer documented as idempotent
  #                        abort at preflight, on every real host.
  #
  # Instantiated units (sing-box@foo.service) are still worth refusing, but only
  # when they are actually enabled; a disabled instance races on nothing.
  local foreign_units="" unit
  while read -r unit; do
    [[ -n "$unit" ]] || continue
    case "$unit" in
      sing-box.service | 'sing-box@.service') continue ;;
    esac
    if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
      foreign_units+="${foreign_units:+$'\n'}$unit"
    fi
  done < <(systemctl list-unit-files --type=service 2>/dev/null |
    awk '/^sing-box.*\.service/ {print $1}')
  if [[ -n "$foreign_units" ]]; then
    die "Detected pre-existing sing-box systemd unit(s) under a non-default name:
$foreign_units

This installer manages sing-box via the default 'sing-box.service' unit.
Running it alongside another unit would race on ports and config paths.
Either disable/remove those units first, or do not install via this script."
  fi

  local mem_kib
  mem_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  if ((mem_kib < 400 * 1024)); then
    warn "Low RAM (${mem_kib} kiB). 512 MiB+ recommended; swap will be added."
  fi

  # Verify the REALITY camouflage target (SNI) speaks TLS 1.3 and is reachable
  # from this host before generating configs. A dead or TLS-1.2-only SNI causes
  # silent REALITY handshake failures on every client while sing-box logs nothing.
  if [[ "$DRY_RUN" != "1" && -n "${SNI:-}" ]] && command -v openssl >/dev/null 2>&1; then
    if echo | timeout 5 openssl s_client -connect "${SNI}:443" -servername "${SNI}" \
      -tls1_3 2>/dev/null | grep -qE "Protocol[[:space:]]*:[[:space:]]*TLSv1\.3|New,[[:space:]]*TLSv1\.3"; then
      ok "REALITY SNI target ${SNI}:443 reachable over TLS 1.3"
    else
      warn "Could not verify TLS 1.3 handshake to ${SNI}:443 within 5s — verify ${SNI} is reachable and supports TLS 1.3"
    fi
  fi

  ok "Preflight done"
}

# ── Base packages ────────────────────────────────────────────────────────
phase_system_init() {
  step "Installing base packages"

  run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  run env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install \
    curl wget ca-certificates gnupg lsb-release unzip jq uuid-runtime \
    ufw fail2ban chrony python3 iproute2 logrotate

  if [[ -n "${TIMEZONE:-}" ]]; then
    run timedatectl set-timezone "$TIMEZONE"
    ok "Timezone: $TIMEZONE"
  fi

  step "Applying kernel network tuning"
  # ONE file, deliberately.
  #
  # /etc/sysctl.d/ is loaded in filename order and later files silently
  # override earlier ones. A host audited during this project had five
  # `99-*.conf` files with fourteen keys defined more than once, including
  # tcp_congestion_control in two of them — so editing the obvious file and
  # seeing no effect was guaranteed, with nothing to indicate why. Splitting
  # this across 99-bbr.conf / 99-swap-tuning.conf was the first step down that
  # road, so both are folded in here and the old files removed.
  #
  # Anything added later must go in THIS file, and must be verified with
  # `sysctl -n <key>` afterwards — never by re-reading the file you edited.
  for stale in /etc/sysctl.d/99-bbr.conf /etc/sysctl.d/99-swap-tuning.conf; do
    if [[ -f "$stale" ]]; then
      run rm -f "$stale"
      info "removed $stale (folded into 99-anyreality.conf)"
    fi
  done
  write_file /etc/sysctl.d/99-anyreality.conf 0644 <<'EOF'
# Managed by anyreality-resi-stack. Verify with `sysctl -n <key>`, not by
# reading this file — a later /etc/sysctl.d/ file would override it silently.

# Congestion control and queueing.
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1

# Long-lived tunnels go idle between bursts. Left at 1, the congestion window
# is reset after every idle period and each burst restarts in slow start —
# very visible on a 200 ms cross-border path.
net.ipv4.tcp_slow_start_after_idle=0

# Cross-border bandwidth-delay product: ~200 ms at 1 Gbps is ~25 MB in flight.
# Default socket buffers cap throughput long before the link does. 32 MB.
net.core.rmem_max=33554432
net.core.wmem_max=33554432
net.core.rmem_default=1048576
net.core.wmem_default=1048576
net.core.optmem_max=65536
net.ipv4.tcp_rmem=4096 87380 33554432
net.ipv4.tcp_wmem=4096 65536 33554432
net.ipv4.udp_rmem_min=16384
net.ipv4.udp_wmem_min=16384

# Domestic CGNAT reclaims idle TCP mappings in roughly 30–90 s. Keepalives have
# to beat that or every idle tunnel comes back dead and the user sees "connected
# but nothing loads" until something forces a reconnect.
net.ipv4.tcp_keepalive_time=60
net.ipv4.tcp_keepalive_intvl=15
net.ipv4.tcp_keepalive_probes=4

# Give up on a dead peer sooner than the ~15 min default; on a lossy path that
# default keeps a hopeless connection occupying the client's slot for minutes.
net.ipv4.tcp_retries2=8

# Cap the socket write queue so latency-sensitive streams are not stuck behind
# a bulk transfer already queued in the kernel.
net.ipv4.tcp_notsent_lowat=131072

# Hysteria2/QUIC is UDP: without a bigger receive queue the kernel drops
# datagrams under load and the loss looks like a bad network path.
net.core.netdev_max_backlog=16384
net.core.somaxconn=8192

# Swap only under real pressure (the installer adds 2 GiB below).
vm.swappiness=10
EOF
  run sysctl --system >/dev/null
  # Verify the EFFECTIVE value, which is the only thing that is true.
  if [[ "$DRY_RUN" != "1" ]]; then
    local key want got drift=0
    while read -r key want; do
      [[ -n "$key" ]] || continue
      got="$(sysctl -n "$key" 2>/dev/null || true)"
      if [[ "$got" != "$want" ]]; then
        warn "sysctl $key is '$got', expected '$want' — another /etc/sysctl.d/ file overrides it"
        drift=$((drift + 1))
      fi
    done <<'KEYS'
net.ipv4.tcp_congestion_control bbr
net.core.default_qdisc fq
net.ipv4.tcp_slow_start_after_idle 0
net.ipv4.tcp_keepalive_time 60
net.ipv4.udp_rmem_min 16384
net.ipv4.udp_wmem_min 16384
KEYS
    ((drift == 0)) && ok "Kernel tuning verified live (bbr/fq/keepalive/udp-buffers)" ||
      warn "$drift kernel parameter(s) did not take effect — check: grep -rn <key> /etc/sysctl.d/"
    if [[ -n "${INTERFACE:-}" ]] && command -v ethtool >/dev/null 2>&1; then
      ethtool -K "$INTERFACE" gro on gso on >/dev/null 2>&1 || true
    fi
  fi

  step "Adding 2 GiB swap (if absent)"
  if [[ ! -f /swapfile ]]; then
    run fallocate -l 2G /swapfile
    run chmod 600 /swapfile
    run mkswap /swapfile >/dev/null
    run swapon /swapfile
    ensure_line "/swapfile none swap sw 0 0" /etc/fstab
    ok "Swap added"
  else
    info "/swapfile exists — skip"
  fi
  step "Limiting journald log volume"
  write_file /etc/systemd/journald.conf.d/99-limits.conf 0644 <<'EOF'
[Journal]
SystemMaxUse=100M
SystemKeepFree=500M
MaxRetentionSec=14day
Compress=yes
EOF
  svc_restart systemd-journald

  step "Enabling chrony (time sync)"
  svc_enable_now chrony

  ok "System init done"
}

# ── Firewall ─────────────────────────────────────────────────────────────
phase_firewall() {
  step "Configuring UFW"

  run ufw default deny incoming
  run ufw default allow outgoing
  run ufw allow "${INBOUND_PORT}/tcp"
  if [[ -n "${SSH_PORT:-}" ]]; then
    run ufw allow "${SSH_PORT}/tcp"
  fi

  # Anti-lockout: `--ssh-port N` only tells UFW which port to keep open, it does
  # not move sshd (that is `--harden-ssh`). Passing a port sshd is not actually
  # listening on would otherwise fence us out the moment `ufw --force enable`
  # runs. Always allow whatever sshd is really bound to as well.
  local live_ssh_ports port
  live_ssh_ports="$(ss -tlnpH 2>/dev/null |
    awk '/"sshd"/ {split($4, a, ":"); print a[length(a)]}' | sort -un || true)"
  for port in $live_ssh_ports; do
    if [[ "$port" != "${SSH_PORT:-}" ]]; then
      warn "sshd is listening on tcp/$port but --ssh-port is '${SSH_PORT:-unset}' — allowing tcp/$port too to avoid lockout"
      run ufw allow "${port}/tcp"
    fi
  done
  # UFW rules are per-protocol: `ufw allow 443` opens TCP only. A Hysteria2
  # inbound behind a TCP-only rule listens happily and is unreachable from
  # every client, and nothing on the server says so — this exact mistake has
  # cost hours more than once, so the `/udp` suffix is explicit here and the
  # verify phase asserts it afterwards.
  if [[ "${WITH_HYSTERIA2:-0}" == "1" ]]; then
    run ufw allow "${HY2_PORT:-$INBOUND_PORT}/udp"
  fi

  # The CDN origin-pull port is opened to the CDN's own ranges only. Left open
  # to the world it is a second, unauthenticated way to reach the relay and a
  # trivially fingerprintable one. Never fail-open to 0.0.0.0/0 on a transient
  # fetch error: fall back to the pinned official Cloudflare IPv4 + IPv6 CIDRs.
  if [[ -n "${CDN_DOMAIN:-}" ]]; then
    local cf_v4 cf_v6 cidr count=0
    cf_v4="$(curl -fsS --max-time 10 https://www.cloudflare.com/ips-v4 2>/dev/null || true)"
    if [[ -z "$cf_v4" ]]; then
      warn "Could not fetch https://www.cloudflare.com/ips-v4 — using pinned official Cloudflare IPv4 CIDRs"
      cf_v4="103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 104.16.0.0/13 104.24.0.0/14 108.162.192.0/18 131.0.72.0/22 141.101.64.0/18 162.158.0.0/15 172.64.0.0/13 173.245.48.0/20 188.114.96.0/20 190.93.240.0/20 197.234.240.0/22 198.41.128.0/17"
    fi
    cf_v6="$(curl -fsS --max-time 10 https://www.cloudflare.com/ips-v6 2>/dev/null || true)"
    if [[ -z "$cf_v6" ]]; then
      cf_v6="2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32"
    fi
    for cidr in $cf_v4 $cf_v6; do
      run ufw allow from "$cidr" to any port "${CDN_ORIGIN_PORT}" proto tcp
      count=$((count + 1))
    done
    ok "Origin-pull port ${CDN_ORIGIN_PORT}/tcp restricted to $count Cloudflare IPv4/IPv6 ranges"
  fi

  if [[ "${WITH_SUBSCRIPTION:-0}" == "1" || "${WITH_AGGREGATOR:-0}" == "1" ]]; then
    run ufw allow 80/tcp
  fi
  run ufw --force enable
  ok "UFW configured"

  step "Configuring fail2ban (sshd jail)"
  local jail="/etc/fail2ban/jail.d/sshd.local"
  write_file "$jail" 0644 <<EOF
[sshd]
enabled = true
port = ${SSH_PORT:-22}
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
  svc_enable_now fail2ban
  svc_restart fail2ban
  ok "fail2ban configured"
}

# ── Operator tooling ─────────────────────────────────────────────────────
# Install the read-only health check and the token-rotation helper onto the
# box itself. Both are needed exactly when the repo checkout is not at hand:
# during an incident, over a phone SSH session, or from cron.
phase_ops_tools() {
  step "Installing operator tools"

  run install -m 0755 "$REPO_ROOT/scripts/healthcheck.sh" \
    /usr/local/sbin/anyreality-resi-stack-healthcheck
  run install -m 0755 "$REPO_ROOT/scripts/rotate-sub-token.sh" \
    /usr/local/sbin/anyreality-resi-stack-rotate-sub-token
  run install -m 0755 "$REPO_ROOT/scripts/warp_egress.py" \
    /usr/local/sbin/anyreality-resi-stack-warp

  # The profile builder, its validator and the rule-set refresher have to live
  # on the box, not only in a checkout: the weekly timer runs them, and so does
  # whoever is holding a phone during an incident.
  run install -d -m 0755 "$LIB_DIR"
  local tool
  for tool in build_profile.py check_profile.py check_sysctl.py ws_ping_inject.py \
    warp_egress.py fetch-rulesets.sh rebuild-profiles.sh altport-redirect.sh; do
    run install -m 0755 "$REPO_ROOT/scripts/$tool" "$LIB_DIR/$tool"
  done
  # build_profile.py looks for data/geosite-cn-extra.json next to itself, so
  # the data dir has to come along.
  run install -d -m 0755 "$LIB_DIR/data"
  run install -m 0644 "$REPO_ROOT/data/geosite-cn-extra.json" "$LIB_DIR/data/geosite-cn-extra.json"

  ok "anyreality-resi-stack-healthcheck / -rotate-sub-token installed to /usr/local/sbin"
  info "profile builder + validators installed to $LIB_DIR"
  info "Cron alerting (mails only on failure): */10 * * * * /usr/local/sbin/anyreality-resi-stack-healthcheck --quiet"
}

# ── Alternate ports ──────────────────────────────────────────────────────
# See scripts/altport-redirect.sh for why these are NAT redirects rather than
# extra inbounds, and why they never show up in `ss -tlnp`.
phase_altports() {
  local alt="${ALT_PORTS:-none}"
  if [[ "$alt" == "none" || -z "$alt" ]]; then
    info "Alternate ports disabled"
    return 0
  fi
  step "Configuring alternate ports ($alt)"

  run env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install iptables

  # UDP alternates only make sense while Hysteria2 is installed, and only for
  # ports low enough to be plausible: 40443 as a UDP alternate is pointless
  # because nothing legitimately speaks QUIC there.
  local udp_alt=""
  if [[ "${WITH_HYSTERIA2:-0}" == "1" ]]; then
    local port
    for port in ${alt//,/ }; do
      case "$port" in
        2096 | 8880 | 8443 | 2053 | 2083 | 2087) udp_alt="${udp_alt:+$udp_alt,}$port" ;;
      esac
    done
  fi

  # The profile must list exactly the UDP alternates that were created here;
  # advertising a port with no redirect behind it gives the client a member
  # that always fails its latency probe.
  ALT_UDP_PORTS_FOR_PROFILE="$udp_alt"
  export ALT_UDP_PORTS_FOR_PROFILE

  write_file /etc/anyreality-resi-stack/altport.env 0644 <<EOF
ALT_TCP_PORTS=$alt
ALT_UDP_PORTS=$udp_alt
TARGET_TCP_PORT=$INBOUND_PORT
TARGET_UDP_PORT=${HY2_PORT:-$INBOUND_PORT}
EOF

  run install -d -m 0755 "$LIB_DIR"
  run install -m 0755 "$REPO_ROOT/scripts/altport-redirect.sh" "$LIB_DIR/altport-redirect.sh"
  run cp "$REPO_ROOT/templates/systemd/altport-redirect.service" \
    /etc/systemd/system/altport-redirect.service
  svc_enable_now altport-redirect

  if [[ "$DRY_RUN" != "1" ]]; then
    local rules
    rules="$(iptables -t nat -S ANYREALITY_ALTPORT 2>/dev/null | grep -c -- '-A' || true)"
    if ((rules > 0)); then
      ok "$rules NAT redirect rule(s) active (tcp -> $INBOUND_PORT, udp -> ${HY2_PORT:-$INBOUND_PORT})"
    else
      warn "No NAT redirect rules found — check: systemctl status altport-redirect"
    fi
  fi
}

# ── CDN relay path ───────────────────────────────────────────────────────
# nginx terminates TLS on the origin-pull port and hands the WebSocket to the
# ping injector, which hands it to sing-box. Three processes on the data path,
# so all three are health-checked; an undocumented process on a data path is
# how the injector once ran for weeks while nobody could see it during an
# outage.
phase_cdn_relay() {
  [[ -n "${CDN_DOMAIN:-}" ]] || return 0
  step "Configuring the CDN WebSocket relay ($CDN_DOMAIN)"

  run env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install nginx

  CDN_CERT_PATH="$CDN_CERT"
  CDN_KEY_PATH="$CDN_KEY"
  export CDN_CERT_PATH CDN_KEY_PATH CDN_DOMAIN CDN_ORIGIN_PORT CDN_WS_PATH

  render_template "$REPO_ROOT/templates/nginx/cdn-origin.conf.tmpl" \
    /etc/nginx/sites-available/anyreality-cdn-origin.conf 0644
  # A real symlink, checked as a symlink. Replacing one of these with a regular
  # copy is a classic silent-drift bug: nginx keeps serving whatever the copy
  # says while the file everyone edits has moved on.
  run ln -sfn /etc/nginx/sites-available/anyreality-cdn-origin.conf \
    /etc/nginx/sites-enabled/anyreality-cdn-origin.conf

  run install -d -m 0755 "$LIB_DIR"
  run install -m 0755 "$REPO_ROOT/scripts/ws_ping_inject.py" "$LIB_DIR/ws_ping_inject.py"
  write_file /etc/anyreality-resi-stack/ws-ping-inject.env 0644 <<'EOF'
# Must stay well under the CDN's ~100s idle timeout for a proxied WebSocket.
WS_PING_INTERVAL=25
WS_PING_LISTEN_PORT=18444
WS_PING_BACKEND_PORT=18443
EOF
  run cp "$REPO_ROOT/templates/systemd/ws-ping-inject.service" \
    /etc/systemd/system/ws-ping-inject.service
  svc_enable_now ws-ping-inject

  if [[ "$DRY_RUN" != "1" ]]; then
    nginx -t >/dev/null 2>&1 || die "nginx rejected the generated vhost; not reloading"
    run systemctl reload nginx
    # Verify the RUNNING config, not the file we just wrote. `nginx -t` only
    # says the syntax parses; `nginx -T` prints what the process actually has.
    if nginx -T 2>/dev/null | grep -q "$CDN_WS_PATH"; then
      ok "nginx is serving the relay path on :${CDN_ORIGIN_PORT}"
    else
      warn "The relay path is not in nginx's running config — check sites-enabled/"
    fi
  fi

  info "Point the CDN at this host with proxying ON, TLS mode Full, and origin port ${CDN_ORIGIN_PORT}"
}

# ── Optional: SSH hardening ──────────────────────────────────────────────
# Only runs when --harden-ssh was passed. Prints loud warnings.
phase_ssh_hardening() {
  step "SSH hardening (--harden-ssh)"
  warn "Make sure you have a working SSH session in another window before continuing."
  warn "Misconfigured SSH can lock you out of the server."

  write_file /etc/ssh/sshd_config.d/99-root-keyonly.conf 0644 <<'EOF'
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF

  if [[ -n "${SSH_PORT:-}" && "$SSH_PORT" != "22" ]]; then
    if grep -q '^Port ' /etc/ssh/sshd_config 2>/dev/null; then
      run sed -i "s/^Port .*/Port ${SSH_PORT}/" /etc/ssh/sshd_config
    else
      ensure_line "Port ${SSH_PORT}" /etc/ssh/sshd_config
    fi
    ok "SSH port -> ${SSH_PORT}"
  fi

  if [[ "$DRY_RUN" != "1" ]]; then
    sshd -t || die "sshd config test failed; aborting before reload"
  fi
  run systemctl reload ssh 2>/dev/null || run systemctl reload sshd
  ok "SSH reloaded"
}
