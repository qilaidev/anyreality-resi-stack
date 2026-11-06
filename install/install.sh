#!/usr/bin/env bash
# anyreality-resi-stack installer.
#
# Quick install:
#   bash <(curl -fsSL https://raw.githubusercontent.com/qilaidev/anyreality-resi-stack/main/install/install.sh) \
#     --node-name "US-Resi-01" --sni addons.mozilla.org
#
# Flags:
#   --node-name NAME            Display name shown in clients (required)
#   --protocol NAME             vless-reality (default) | anytls-reality (sing-box only)
#   --sni HOST                  Reality SNI (default: addons.mozilla.org)
#   --short-id HEX              Reality short_id (0-16 even hex chars; default: random 8-byte hex on new install)
#   --inbound-port N            Listen port (default: 443)
#
#  Multi-path & Egress options (why: docs/en/CHINA-NETWORK.md, docs/en/WARP-EGRESS.md)
#   --alt-ports LIST            Extra ports REDIRECTed to the inbound
#                               (default: 2096,8880,40443; "none" to disable)
#   --no-hysteria2              Do not install the UDP/QUIC fallback path
#   --hy2-port N                Hysteria2 UDP port (default: --inbound-port)
#   --cdn-domain HOST           Enable the CDN WebSocket relay path for this
#                               domain (must be proxied by the CDN)
#   --cdn-cert FILE             TLS certificate for the CDN origin vhost
#   --cdn-key FILE              Private key for --cdn-cert
#   --cdn-origin-port N         Origin-pull port (default: 8443)
#   --cdn-ips LIST              Comma-separated CDN edge IPs to pin in the
#                               profile (default: a spread of Cloudflare edges;
#                               re-pick per line with scripts/pick-cf-ip.py)
#   --with-warp                 Enable selective Cloudflare WARP WireGuard egress
#                               for AI/Turnstile/anti-challenge domains + watchdog
#   --warp-config FILE          Pre-registered WARP credentials JSON (optional;
#                               auto-registers a free WARP keypair when omitted)
#   --allow-quic                Do not reject client udp/443 (see docs)
#   --ssh-port N                SSH port if you want UFW to keep it open (default: 22)
#   --timezone TZ               e.g. America/Los_Angeles (optional)
#   --interface NAME            NIC for traffic accounting (default: auto-detect)
#   --total-bytes N             Plan quota for the subscription card (default: 0 = hide)
#   --billing-cycle-day N       Provider reset day for usage accounting (default: 1)
#   --usage-poll-interval N     Background usage sample interval seconds (default: 60)
#   --with-subscription         Install the subscription leaf server on :80
#   --with-aggregator URL       Install aggregator instead, polling URL for /status
#   --sub-tls-cert FILE         Serve the subscription over HTTPS with this certificate
#   --sub-tls-key FILE          Private key for --sub-tls-cert (both or neither)
#   --harden-ssh                Apply SSH key-only + port change (read warnings!)
#   --singbox-version X.Y.Z     Pin sing-box version (default: apt latest stable)
#   --dry-run                   Print every action, change nothing
#   --non-interactive           Refuse to prompt (use with --config)
#   --config FILE               Source a file with all the above as KEY=VALUE
#   --uninstall                 Tear down (calls uninstall.sh)
#   --help                      This message
#
# Environment:
#   ANYREALITY_RESI_STACK_REF   Branch/tag for remote-piped installs (default: main;
#                               legacy REALITY_RESI_STACK_REF is still honored)

set -Eeuo pipefail

# ── Self-locate the repo (handles both clone-and-run and curl-piped use) ─
REPO_DIR=/opt/anyreality-resi-stack
# Primary env var is ANYREALITY_RESI_STACK_REF; the legacy REALITY_RESI_STACK_REF
# is still accepted as a fallback so old curl-piped commands keep working.
ANYREALITY_RESI_STACK_REF="${ANYREALITY_RESI_STACK_REF:-${REALITY_RESI_STACK_REF:-main}}"
SCRIPT_PATH="${BASH_SOURCE[0]:-}"

# When invoked via `bash <(curl ...)`, BASH_SOURCE is /dev/fd/<n> — we need
# to fetch the full repo before we can source lib/*.sh and read templates/.
if [[ -z "$SCRIPT_PATH" || "$SCRIPT_PATH" == /dev/fd/* || "$SCRIPT_PATH" == /proc/* ]]; then
  echo ">> Detected remote-piped run — fetching ref ${ANYREALITY_RESI_STACK_REF} to $REPO_DIR…"
  if ! command -v git >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq git
  fi
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" fetch --depth 1 origin "$ANYREALITY_RESI_STACK_REF"
    git -C "$REPO_DIR" reset --hard FETCH_HEAD
  else
    rm -rf "$REPO_DIR"
    git clone --depth 1 --branch "$ANYREALITY_RESI_STACK_REF" \
      https://github.com/qilaidev/anyreality-resi-stack.git "$REPO_DIR"
  fi
  exec bash "$REPO_DIR/install/install.sh" "$@"
fi

REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
export REPO_ROOT

COMMON_SH_LOADED=1
export COMMON_SH_LOADED
# shellcheck source=lib/common.sh
. "$REPO_ROOT/install/lib/common.sh"
# shellcheck source=lib/system.sh
. "$REPO_ROOT/install/lib/system.sh"
# shellcheck source=lib/singbox.sh
. "$REPO_ROOT/install/lib/singbox.sh"
# shellcheck source=lib/subscription.sh
. "$REPO_ROOT/install/lib/subscription.sh"
# shellcheck source=lib/backup.sh
. "$REPO_ROOT/install/lib/backup.sh"

# ── Defaults ─────────────────────────────────────────────────────────────
NODE_NAME=""
# vless-reality (VLESS + Reality + xtls-rprx-vision) is the default because it
# is the only one of the two that every client kernel can express. AnyReality
# is still supported and still has the better padding story, but mihomo's
# `anytls` block has no `reality-opts` field: on a Clash client the node cannot
# be written down at all. That failure is silent from the server's side — the
# config validates, the service is green, and Clash users simply have no node.
PROTOCOL="vless-reality"
# Whether the operator actually asked for a protocol. An upgrade must never
# change one silently: a host installed under the previous default (AnyReality)
# would otherwise be switched to VLESS by the mere act of re-running the
# installer, and every client that already imported the AnyTLS password would
# stop connecting — with the server looking perfectly healthy.
PROTOCOL_EXPLICIT=0
SNI="addons.mozilla.org"
INBOUND_PORT=443
# Alternate ports are NAT REDIRECTs to INBOUND_PORT, not extra listeners.
# Interference is per-port and per-carrier and it moves: 443 was once the only
# usable port on a line where every high port was dead, and five weeks later on
# the same line 443 was three times slower than 8880. Expose several, let the
# client race them.
ALT_PORTS="2096,8880,40443"
WITH_HYSTERIA2=1
HY2_PORT=""
CDN_DOMAIN=""
CDN_CERT=""
CDN_KEY=""
CDN_ORIGIN_PORT=8443
# A spread of Cloudflare edge ranges, deliberately from different /8s. These
# are a starting point, not an optimum: which edge is fast depends on the
# client's carrier and province, and the same IP lands in Hong Kong for one
# line and in the US for another. Re-pick per line with scripts/pick-cf-ip.py.
CDN_IPS="104.17.48.94,190.93.244.73,141.101.114.16,173.245.49.46"
ALLOW_QUIC=0
SHORT_ID=""
WITH_WARP=0
WARP_CONFIG=""
SSH_PORT=22
TIMEZONE=""
INTERFACE=""
TOTAL_BYTES=0
EXPIRE_TS=0
USAGE_OFFSET_BYTES=0
BILLING_CYCLE_DAY=1
USAGE_POLL_INTERVAL_SECONDS=60
COUNT_CURRENT_BOOT_ON_INIT=true
UPDATE_INTERVAL_HOURS=24
CACHE_TTL_SECONDS=60
REMOTE_POLL_INTERVAL_SECONDS=60
REMOTE_TIMEOUT_SECONDS=3
MAX_REMOTE_STATUS_BYTES=65536
REQUEST_TIMEOUT_SECONDS=10
WITH_SUBSCRIPTION=0
WITH_AGGREGATOR=0
REMOTE_STATUS_URL=""
SUB_TLS_CERT=""
SUB_TLS_KEY=""
HARDEN_SSH=0
SINGBOX_VERSION=""
DRY_RUN=0
NON_INTERACTIVE=0
DO_UNINSTALL=0
CONFIG_FILE=""

print_help() { sed -n '/^# anyreality-resi-stack installer\./,/^set -Eeuo/{ /^set -Eeuo/d; s/^# \{0,1\}//; p; }' "$0"; }

# ── Argument parsing ─────────────────────────────────────────────────────
# Flags that consume the next argv entry. Without this guard `--sni` as the last
# argument dies with a bare `$2: unbound variable` from `set -u`, which tells the
# operator nothing about which flag was malformed.
VALUE_FLAGS=" --node-name --protocol --sni --short-id --inbound-port --ssh-port --timezone --interface --total-bytes --billing-cycle-day --usage-poll-interval --with-aggregator --sub-tls-cert --sub-tls-key --singbox-version --config --alt-ports --hy2-port --cdn-domain --cdn-cert --cdn-key --cdn-origin-port --cdn-ips --warp-config "

while [[ $# -gt 0 ]]; do
  if [[ "$VALUE_FLAGS" == *" $1 "* && $# -lt 2 ]]; then
    die "$1 requires a value (try --help)"
  fi
  case "$1" in
    --node-name)
      NODE_NAME="$2"
      shift 2
      ;;
    --protocol)
      PROTOCOL="$2"
      PROTOCOL_EXPLICIT=1
      shift 2
      ;;
    --sni)
      SNI="$2"
      shift 2
      ;;
    --short-id)
      SHORT_ID="$2"
      shift 2
      ;;
    --inbound-port)
      INBOUND_PORT="$2"
      shift 2
      ;;
    --ssh-port)
      SSH_PORT="$2"
      shift 2
      ;;
    --timezone)
      TIMEZONE="$2"
      shift 2
      ;;
    --interface)
      INTERFACE="$2"
      shift 2
      ;;
    --total-bytes)
      TOTAL_BYTES="$2"
      shift 2
      ;;
    --billing-cycle-day)
      BILLING_CYCLE_DAY="$2"
      shift 2
      ;;
    --usage-poll-interval)
      USAGE_POLL_INTERVAL_SECONDS="$2"
      REMOTE_POLL_INTERVAL_SECONDS="$2"
      shift 2
      ;;
    --with-subscription)
      WITH_SUBSCRIPTION=1
      shift
      ;;
    --with-aggregator)
      WITH_AGGREGATOR=1
      REMOTE_STATUS_URL="$2"
      shift 2
      ;;
    --sub-tls-cert)
      SUB_TLS_CERT="$2"
      shift 2
      ;;
    --sub-tls-key)
      SUB_TLS_KEY="$2"
      shift 2
      ;;
    --alt-ports)
      ALT_PORTS="$2"
      shift 2
      ;;
    --no-alt-ports)
      ALT_PORTS="none"
      shift
      ;;
    --no-hysteria2)
      WITH_HYSTERIA2=0
      shift
      ;;
    --hy2-port)
      HY2_PORT="$2"
      shift 2
      ;;
    --cdn-domain)
      CDN_DOMAIN="$2"
      shift 2
      ;;
    --cdn-cert)
      CDN_CERT="$2"
      shift 2
      ;;
    --cdn-key)
      CDN_KEY="$2"
      shift 2
      ;;
    --cdn-origin-port)
      CDN_ORIGIN_PORT="$2"
      shift 2
      ;;
    --cdn-ips)
      CDN_IPS="$2"
      shift 2
      ;;
    --allow-quic)
      ALLOW_QUIC=1
      shift
      ;;
    --with-warp)
      WITH_WARP=1
      shift
      ;;
    --warp-config)
      WARP_CONFIG="$2"
      WITH_WARP=1
      shift 2
      ;;
    --harden-ssh)
      HARDEN_SSH=1
      shift
      ;;
    --singbox-version)
      SINGBOX_VERSION="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --uninstall)
      DO_UNINSTALL=1
      shift
      ;;
    -h | --help)
      print_help
      exit 0
      ;;
    *) die "Unknown arg: $1 (try --help)" ;;
  esac
done

if [[ -n "$CONFIG_FILE" ]]; then
  [[ -f "$CONFIG_FILE" ]] || die "Config file not found: $CONFIG_FILE"
  # A PROTOCOL line in the config file is as explicit as the flag.
  if grep -qE '^[[:space:]]*PROTOCOL=' "$CONFIG_FILE"; then
    PROTOCOL_EXPLICIT=1
  fi
  # shellcheck source=/dev/null
  . "$CONFIG_FILE"
fi

# Upgrade safety: an existing inbound decides the protocol unless the operator
# said otherwise. Re-running the installer is the documented way to update, so
# it must not be a way to lose every client.
if [[ "$PROTOCOL_EXPLICIT" == "0" && -f /etc/sing-box/conf/11_anytls-reality_inbounds.json ]]; then
  PROTOCOL="anytls-reality"
  warn "Existing AnyReality inbound found — keeping --protocol anytls-reality."
  warn "The default for NEW installs is now vless-reality, because mihomo cannot"
  warn "express an AnyTLS+REALITY node at all. To switch, re-run with"
  warn "--protocol vless-reality — every client must then re-import."
fi

export DRY_RUN

if [[ "$DO_UNINSTALL" == "1" ]]; then
  exec bash "$REPO_ROOT/install/uninstall.sh"
fi

if [[ "$WITH_SUBSCRIPTION" == "1" && "$WITH_AGGREGATOR" == "1" ]]; then
  die "--with-subscription and --with-aggregator are mutually exclusive"
fi

require_binary_flag() {
  local name="$1" value="$2"
  [[ "$value" == "0" || "$value" == "1" ]] || die "$name must be 0 or 1, got: $value"
}

require_uint() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$name must be a non-negative integer, got: $value"
}

require_int() {
  local name="$1" value="$2"
  [[ "$value" =~ ^-?[0-9]+$ ]] || die "$name must be an integer, got: $value"
}

require_port() {
  local name="$1" value="$2"
  require_uint "$name" "$value"
  ((value >= 1 && value <= 65535)) || die "$name must be between 1 and 65535, got: $value"
}

require_min_uint() {
  local name="$1" value="$2" min="$3"
  require_uint "$name" "$value"
  ((value >= min)) || die "$name must be >= $min, got: $value"
}

require_safe_label() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9._\ -]+$ ]] ||
    die "$name may contain only letters, numbers, space, dot, underscore, or hyphen: $value"
}

require_safe_host() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9.-]+$ && "$value" != .* && "$value" != *. ]] ||
    die "$name must be a hostname or IPv4 address without spaces or URL syntax: $value"
}

require_safe_interface() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9_.:-]+$ ]] ||
    die "$name has unsafe characters for /sys/class/net lookup: $value"
}

require_bool_word() {
  local name="$1" value="$2"
  case "$value" in
    1 | 0 | true | false | yes | no | TRUE | FALSE | YES | NO | True | False | Yes | No) ;;
    *) die "$name must be true/false/yes/no/1/0, got: $value" ;;
  esac
}

validate_config() {
  require_binary_flag WITH_SUBSCRIPTION "$WITH_SUBSCRIPTION"
  require_binary_flag WITH_AGGREGATOR "$WITH_AGGREGATOR"
  require_binary_flag HARDEN_SSH "$HARDEN_SSH"
  require_port INBOUND_PORT "$INBOUND_PORT"
  [[ -z "$SSH_PORT" ]] || require_port SSH_PORT "$SSH_PORT"
  require_uint TOTAL_BYTES "$TOTAL_BYTES"
  require_uint EXPIRE_TS "$EXPIRE_TS"
  require_int USAGE_OFFSET_BYTES "$USAGE_OFFSET_BYTES"
  require_uint BILLING_CYCLE_DAY "$BILLING_CYCLE_DAY"
  ((BILLING_CYCLE_DAY >= 1 && BILLING_CYCLE_DAY <= 28)) ||
    die "BILLING_CYCLE_DAY must be 1..28, got: $BILLING_CYCLE_DAY"
  require_min_uint USAGE_POLL_INTERVAL_SECONDS "$USAGE_POLL_INTERVAL_SECONDS" 5
  require_min_uint UPDATE_INTERVAL_HOURS "$UPDATE_INTERVAL_HOURS" 1
  require_min_uint CACHE_TTL_SECONDS "$CACHE_TTL_SECONDS" 5
  require_min_uint REMOTE_POLL_INTERVAL_SECONDS "$REMOTE_POLL_INTERVAL_SECONDS" 5
  require_min_uint REMOTE_TIMEOUT_SECONDS "$REMOTE_TIMEOUT_SECONDS" 1
  require_min_uint MAX_REMOTE_STATUS_BYTES "$MAX_REMOTE_STATUS_BYTES" 1024
  require_min_uint REQUEST_TIMEOUT_SECONDS "$REQUEST_TIMEOUT_SECONDS" 1
  require_bool_word COUNT_CURRENT_BOOT_ON_INIT "$COUNT_CURRENT_BOOT_ON_INIT"
  require_safe_label NODE_NAME "$NODE_NAME"
  case "$PROTOCOL" in
    # vless-vision is the historical spelling of the same inbound; keep it
    # working so existing --config files and docs do not break.
    vless-reality | vless-vision)
      PROTOCOL="vless-reality"
      ;;
    anytls-reality) ;;
    *) die "PROTOCOL must be vless-reality or anytls-reality, got: $PROTOCOL" ;;
  esac
  require_binary_flag WITH_HYSTERIA2 "$WITH_HYSTERIA2"
  require_binary_flag ALLOW_QUIC "$ALLOW_QUIC"
  require_binary_flag WITH_WARP "$WITH_WARP"
  if [[ -n "$SHORT_ID" ]]; then
    [[ "$SHORT_ID" =~ ^[0-9a-fA-F]{1,16}$ && $((${#SHORT_ID} % 2)) -eq 0 ]] ||
      die "SHORT_ID must be 2..16 even-length hex characters, got: $SHORT_ID"
  fi
  if [[ -n "$WARP_CONFIG" && "$DRY_RUN" != "1" ]]; then
    [[ -f "$WARP_CONFIG" ]] || die "--warp-config file not found: $WARP_CONFIG"
  fi
  [[ -z "$HY2_PORT" ]] || require_port HY2_PORT "$HY2_PORT"
  if [[ "$ALT_PORTS" != "none" && -n "$ALT_PORTS" ]]; then
    local alt
    for alt in ${ALT_PORTS//,/ }; do
      require_port "ALT_PORTS entry" "$alt"
    done
  fi
  if [[ -n "$CDN_DOMAIN" ]]; then
    require_safe_host CDN_DOMAIN "$CDN_DOMAIN"
    require_port CDN_ORIGIN_PORT "$CDN_ORIGIN_PORT"
    # Only these ports are pulled from over HTTPS by Cloudflare. Picking any
    # other one produces a vhost that works when tested directly from the
    # server and 522s through the CDN, which reads like an origin failure.
    case "$CDN_ORIGIN_PORT" in
      443 | 2053 | 2083 | 2087 | 2096 | 8443) ;;
      *) die "CDN_ORIGIN_PORT must be one of 443/2053/2083/2087/2096/8443 (CDN HTTPS origin-pull ports), got: $CDN_ORIGIN_PORT" ;;
    esac
    [[ "$CDN_ORIGIN_PORT" != "$INBOUND_PORT" ]] ||
      die "CDN_ORIGIN_PORT cannot equal INBOUND_PORT — sing-box owns that port and forwards every non-proxy connection to its Reality handshake target, so nginx can never see it"
    [[ -n "$CDN_CERT" && -n "$CDN_KEY" ]] ||
      die "--cdn-domain requires --cdn-cert and --cdn-key (a certificate for that hostname)"
    if [[ "$DRY_RUN" != "1" ]]; then
      [[ -f "$CDN_CERT" ]] || die "--cdn-cert file not found: $CDN_CERT"
      [[ -f "$CDN_KEY" ]] || die "--cdn-key file not found: $CDN_KEY"
    fi
    [[ -n "$CDN_IPS" ]] || die "--cdn-domain requires at least one --cdn-ips entry"
    local ip
    for ip in ${CDN_IPS//,/ }; do
      require_safe_host "CDN_IPS entry" "$ip"
    done
  fi
  require_safe_host SNI "$SNI"
  require_safe_interface INTERFACE "$INTERFACE"
  [[ "$DRY_RUN" == "1" || -n "$SERVER_IP" ]] ||
    die "SERVER_IP auto-detection failed; set SERVER_IP in --config and rerun"
  [[ -z "$SERVER_IP" ]] || require_safe_host SERVER_IP "$SERVER_IP"
  [[ -z "$SINGBOX_VERSION" || "$SINGBOX_VERSION" =~ ^[^[:space:]]+$ ]] ||
    die "SINGBOX_VERSION must not contain whitespace"
  if [[ "$WITH_AGGREGATOR" == "1" ]]; then
    [[ "$REMOTE_STATUS_URL" =~ ^https?://[^[:space:]]+$ ]] ||
      die "REMOTE_STATUS_URL must be an http(s) URL without spaces"
  fi
  # TLS for the subscription endpoint is opt-in and needs a real certificate;
  # half a pair is always a mistake, so refuse it rather than silently serving
  # plain HTTP when the operator believed they had enabled HTTPS.
  if [[ -n "$SUB_TLS_CERT" || -n "$SUB_TLS_KEY" ]]; then
    [[ -n "$SUB_TLS_CERT" && -n "$SUB_TLS_KEY" ]] ||
      die "--sub-tls-cert and --sub-tls-key must be given together"
    [[ "$WITH_SUBSCRIPTION" == "1" || "$WITH_AGGREGATOR" == "1" ]] ||
      die "--sub-tls-cert requires --with-subscription or --with-aggregator"
    if [[ "$DRY_RUN" != "1" ]]; then
      [[ -f "$SUB_TLS_CERT" ]] || die "--sub-tls-cert file not found: $SUB_TLS_CERT"
      [[ -f "$SUB_TLS_KEY" ]] || die "--sub-tls-key file not found: $SUB_TLS_KEY"
    fi
  fi
}

# ── Interactive fill-in for required ─────────────────────────────────────
if [[ -z "$NODE_NAME" ]]; then
  if [[ "$NON_INTERACTIVE" == "1" ]]; then
    die "--node-name required in --non-interactive mode"
  fi
  read -rp "Node display name (e.g. US-Resi-01): " NODE_NAME
  [[ -n "$NODE_NAME" ]] || die "Node name cannot be empty"
fi

# Auto-detect NIC if not provided.
if [[ -z "$INTERFACE" ]]; then
  INTERFACE="$(default_interface || true)"
  [[ -n "$INTERFACE" ]] || die "Could not auto-detect interface; pass --interface NAME"
fi

# Pick a sensible server IP for the rendered client profile (auto-detect).
# A single lookup endpoint is a single point of install failure: ipify is
# blocked or rate-limited often enough that installs on fresh hosts fail with
# only a vague warning. Try a few independent providers before giving up.
#
# "Independent" means *different hosting providers*, not just different names.
# The previous list looked like four fallbacks but was effectively one:
# api.ipify.org, icanhazip.com and ipv4.icanhazip.com all resolve into
# Cloudflare ranges (and the last two are literally the same service on the
# same IPs), so a Cloudflare incident took out 3 of 4 at once. Verified
# 2026-08-06. Keep one entry per hosting provider:
#   ifconfig.me           -> Google Cloud
#   checkip.amazonaws.com -> AWS
#   ident.me              -> Hetzner
#   api.ipify.org         -> Cloudflare
detect_public_ip() {
  local url ip
  for url in \
    https://ifconfig.me/ip \
    https://checkip.amazonaws.com \
    https://ident.me \
    https://api.ipify.org; do
    ip="$(curl -fsS --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]')" || ip=""
    if [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
      printf '%s' "$ip"
      return 0
    fi
  done
  return 1
}

if [[ -z "${SERVER_IP:-}" ]]; then
  SERVER_IP="$(detect_public_ip || true)"
fi
if [[ -z "$SERVER_IP" ]]; then
  warn "Could not auto-detect public IP from any provider."
  warn "Set SERVER_IP=… in --config (or export it) so the client profile renders correctly."
fi

validate_config

export SERVER_IP NODE_NAME PROTOCOL SNI INBOUND_PORT SSH_PORT TIMEZONE INTERFACE \
  TOTAL_BYTES EXPIRE_TS USAGE_OFFSET_BYTES WITH_SUBSCRIPTION WITH_AGGREGATOR \
  BILLING_CYCLE_DAY USAGE_POLL_INTERVAL_SECONDS COUNT_CURRENT_BOOT_ON_INIT \
  UPDATE_INTERVAL_HOURS CACHE_TTL_SECONDS REMOTE_POLL_INTERVAL_SECONDS \
  REMOTE_TIMEOUT_SECONDS MAX_REMOTE_STATUS_BYTES REQUEST_TIMEOUT_SECONDS REMOTE_STATUS_URL \
  HARDEN_SSH SINGBOX_VERSION SUB_TLS_CERT SUB_TLS_KEY \
  ALT_PORTS WITH_HYSTERIA2 HY2_PORT CDN_DOMAIN CDN_CERT CDN_KEY \
  CDN_ORIGIN_PORT CDN_IPS ALLOW_QUIC SHORT_ID WITH_WARP WARP_CONFIG

# ── Run phases ───────────────────────────────────────────────────────────
phase_preflight
phase_system_init
phase_install_singbox
phase_migrate_legacy_paths
phase_generate_keys
phase_configure_singbox
phase_logrotate
phase_singbox_service
phase_firewall

# Plain `[[ … ]] && phase … || true` would swallow a real failure inside the
# phase, so branch explicitly: if hardening runs, it must succeed.
if [[ "$HARDEN_SSH" == "1" ]]; then
  phase_ssh_hardening
fi

# Order matters here. The alternate ports and the CDN relay have to exist
# before the profile is built, because the profile advertises exactly the paths
# that were actually created — a member with no listener behind it is a node
# that fails every latency probe. And phase_ops_tools puts the profile builder
# on the box, which the subscription phases then run.
phase_altports
phase_cdn_relay
phase_ops_tools
if [[ "$WITH_WARP" == "1" ]]; then
  phase_warp_egress
fi

if [[ "$WITH_AGGREGATOR" == "1" ]]; then
  phase_subscription_aggregator
elif [[ "$WITH_SUBSCRIPTION" == "1" ]]; then
  phase_subscription_leaf
fi

phase_backup
phase_verify

# ── Final summary ────────────────────────────────────────────────────────
printf "\n"
printf "%s╔══════════════════════════════════════════════════════════════╗%s\n" "$C_GREEN" "$C_RESET"
printf "%s║                  INSTALLATION COMPLETE  ✔                    ║%s\n" "$C_GREEN" "$C_RESET"
printf "%s╚══════════════════════════════════════════════════════════════╝%s\n" "$C_GREEN" "$C_RESET"

if [[ "$DRY_RUN" != "1" ]]; then
  printf "\n%sNode :%s %s\n" "$C_CYAN" "$C_RESET" "$NODE_NAME"
  printf "%sProto:%s %s\n" "$C_CYAN" "$C_RESET" "$PROTOCOL"
  printf "%sIP   :%s %s\n" "$C_CYAN" "$C_RESET" "${SERVER_IP:-<unknown>}"
  printf "%sPort :%s %s\n" "$C_CYAN" "$C_RESET" "$INBOUND_PORT"
  printf "%sSNI  :%s %s\n" "$C_CYAN" "$C_RESET" "$SNI"

  if [[ "$ALT_PORTS" != "none" && -n "$ALT_PORTS" ]]; then
    printf "%sAlt  :%s %s (NAT REDIRECT to %s — they will NOT appear in \`ss -tlnp\`)\n" \
      "$C_CYAN" "$C_RESET" "$ALT_PORTS" "$INBOUND_PORT"
  fi
  if [[ "$WITH_HYSTERIA2" == "1" ]]; then
    printf "%sHy2  :%s udp/%s (salamander obfs, self-signed cert pinned in the profile)\n" \
      "$C_CYAN" "$C_RESET" "${HY2_PORT:-$INBOUND_PORT}"
  fi
  if [[ -n "$CDN_DOMAIN" ]]; then
    printf "%sCDN  :%s %s -> origin :%s -> ws-ping-inject -> sing-box\n" \
      "$C_CYAN" "$C_RESET" "$CDN_DOMAIN" "$CDN_ORIGIN_PORT"
  fi
  if [[ "$WITH_WARP" == "1" ]]; then
    printf "%sWARP :%s selective WireGuard egress (warp-ep + warp-watchdog.timer)\n" \
      "$C_CYAN" "$C_RESET"
  fi

  if [[ "$PROTOCOL" == "vless-reality" ]]; then
    printf "\n%sClient vless:// link (save this — it will not be shown again):%s\n" "$C_YELLOW" "$C_RESET"
    printf "  vless://%s@%s:%s?encryption=none&flow=xtls-rprx-vision&security=reality&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp#%s\n" \
      "$UUID" "$SERVER_IP" "$INBOUND_PORT" "$SNI" "$REALITY_PUBLIC_KEY" "$SHORT_ID" "$NODE_NAME"
    printf "%s  This single link is the direct-REALITY path only. Import the subscription instead to get%s\n" "$C_GRAY" "$C_RESET"
    printf "%s  the Hysteria2 and CDN paths and the automatic failover between them.%s\n" "$C_GRAY" "$C_RESET"
  else
    printf "\n%sAnyReality (AnyTLS + Reality) client credentials — sing-box clients only:%s\n" "$C_YELLOW" "$C_RESET"
    printf "  type=anytls  server=%s  port=%s\n" "${SERVER_IP:-<host>}" "$INBOUND_PORT"
    printf "  password=%s\n" "$ANYTLS_PASSWORD"
    printf "  sni=%s  public-key=%s  short-id=%s  fingerprint=chrome\n" "$SNI" "$REALITY_PUBLIC_KEY" "$SHORT_ID"
    printf "%s  ⚠ mihomo has no reality-opts for anytls, so no Clash profile can be generated at all.%s\n" "$C_YELLOW" "$C_RESET"
    printf "%s    Reinstall with --protocol vless-reality if any of your clients is Clash-based.%s\n" "$C_GRAY" "$C_RESET"
  fi
  if [[ "$WITH_HYSTERIA2" == "1" ]]; then
    printf "\n%sHysteria2 password:%s %s\n" "$C_YELLOW" "$C_RESET" "${HY2_PASSWORD:-<see secrets.env>}"
    printf "%s  obfs=salamander  obfs-password=%s%s\n" "$C_GRAY" "${HY2_OBFS_PASSWORD:-<see secrets.env>}" "$C_RESET"
  fi

  if [[ "$WITH_SUBSCRIPTION" == "1" || "$WITH_AGGREGATOR" == "1" ]]; then
    if [[ -n "$SUB_TLS_CERT" ]]; then
      printf "\n%sSubscription URL:%s https://<your-cert-hostname>/%s\n" \
        "$C_CYAN" "$C_RESET" "$SUB_TOKEN"
      printf "%s  TLS is on — use the hostname the certificate was issued for, not the IP.%s\n" \
        "$C_GRAY" "$C_RESET"
    else
      printf "\n%sSubscription URL:%s http://%s/%s\n" "$C_CYAN" "$C_RESET" "${SERVER_IP:-<host>}" "$SUB_TOKEN"
      printf "%s  Served over plain HTTP — treat this URL as a password. See docs OPERATIONS.md.%s\n" \
        "$C_GRAY" "$C_RESET"
    fi
  fi

  printf "\n%sSecrets stored at /etc/anyreality-resi-stack/secrets.env (mode 600).%s\n" "$C_GRAY" "$C_RESET"
fi
