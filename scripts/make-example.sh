#!/usr/bin/env bash
# make-example.sh — render templates/ with deterministic fake values into examples/.
# Output is committed; CI re-runs this and diff-checks for drift.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEMPLATES="$REPO_ROOT/templates"
EXAMPLES="$REPO_ROOT/examples"

# Deterministic fake values — RFC 5737 docs IPs, all-zero UUID, sentinel keys.
# These are also in scripts/redact.sh ALLOWLIST_PLAINTEXT.
# These vars are consumed via indirect expansion (${!name}) in render().
# shellcheck disable=SC2034
declare_fakes_single() {
  UUID="00000000-0000-0000-0000-000000000000"
  REALITY_PRIVATE_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  REALITY_PUBLIC_KEY="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
  SHORT_ID=""
  SUB_TOKEN="example-token-do-not-use"
  ANYTLS_PASSWORD="example-anytls-password-do-not-use"
  HY2_PASSWORD="example-hy2-password-do-not-use"
  HY2_OBFS_PASSWORD="example-obfs-password-do-not-use"
  CDN_WS_PATH="/example-ws-path"
  SERVER_IP="203.0.113.10"
  SNI="addons.mozilla.org"
  INBOUND_PORT="443"
  NODE_NAME="Example-Resi-01"
}

# shellcheck disable=SC2034
declare_fakes_dual() {
  RESI_UUID="00000000-0000-0000-0000-000000000000"
  RESI_REALITY_PRIVATE_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  RESI_REALITY_PUBLIC_KEY="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
  RESI_SHORT_ID=""
  RESI_ANYTLS_PASSWORD="example-anytls-password-do-not-use"
  RESI_HY2_PASSWORD="example-hy2-password-do-not-use"
  RESI_HY2_OBFS_PASSWORD="example-obfs-password-do-not-use"
  RESI_CDN_WS_PATH="/example-ws-path"
  RESI_SERVER_IP="203.0.113.10"
  RESI_SNI="addons.mozilla.org"
  RESI_INBOUND_PORT="443"
  RESI_NODE_NAME="Example-Resi-01"

  DC_UUID="11111111-1111-1111-1111-111111111111"
  DC_REALITY_PRIVATE_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  DC_REALITY_PUBLIC_KEY="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
  DC_SHORT_ID=""
  DC_ANYTLS_PASSWORD="example-anytls-password-do-not-use"
  DC_SERVER_IP="198.51.100.20"
  DC_SNI="addons.mozilla.org"
  DC_INBOUND_PORT="443"
  DC_NODE_NAME="Example-DC-01"
}

# render <template-file> <output-file>
# Replaces every @@VAR@@ token in template with $VAR from the environment.
# Uses awk for portable, safe substitution (no eval, no envsubst footguns).
render() {
  local in="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  # Collect all @@VAR@@ tokens from the template.
  local vars
  # Digits included: `@@HY2_PASSWORD@@` does not match `[A-Z_]+`.
  vars="$(grep -oE '@@[A-Z0-9_]+@@' "$in" 2>/dev/null | sort -u || true)"

  local tmp
  tmp="$(mktemp)"
  cp "$in" "$tmp"

  local token name value
  while IFS= read -r token; do
    [[ -z "$token" ]] && continue
    name="${token//@/}"
    value="${!name-}"
    if [[ -z "${!name+x}" ]]; then
      echo "render: missing variable for $token in $in" >&2
      rm -f "$tmp"
      exit 1
    fi
    # Use perl-style sed avoid: just use awk for clarity.
    python3 - "$tmp" "$token" "$value" <<'PY'
import sys, pathlib
path, token, value = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
p.write_text(p.read_text().replace(token, value))
PY
  done <<<"$vars"

  local leftover
  leftover="$(grep -oE '@@[A-Za-z0-9_]+@@' "$tmp" 2>/dev/null | sort -u | tr '\n' ' ' || true)"
  if [[ -n "$leftover" ]]; then
    echo "render: $out would still contain unsubstituted token(s): $leftover" >&2
    rm -f "$tmp"
    exit 1
  fi

  mv "$tmp" "$out"
}

# write_params_single <file> — the params the builder consumes. Kept here (not
# shared with the installer) on purpose: the installer's copy has to read live
# secrets and this one must stay deterministic for the committed examples.
write_params_single() {
  cat >"$1" <<EOF
{
  "node_name": "$NODE_NAME",
  "server": "$SERVER_IP",
  "sni": "$SNI",
  "protocol": "vless-reality",
  "uuid": "$UUID",
  "reality_public_key": "$REALITY_PUBLIC_KEY",
  "short_id": "$SHORT_ID",
  "port": $INBOUND_PORT,
  "alt_tcp_ports": [2096, 8880, 40443],
  "allow_quic": false,
  "hysteria2": {
    "enabled": true,
    "port": 443,
    "alt_ports": [2096, 8880],
    "password": "$HY2_PASSWORD",
    "obfs_password": "$HY2_OBFS_PASSWORD",
    "sni": "$SNI"
  },
  "cf_ws": {
    "enabled": true,
    "domain": "example.com",
    "path": "$CDN_WS_PATH",
    "port": 443,
    "uuid": "$UUID",
    "ips": ["203.0.113.20", "203.0.113.21"]
  },
  "dc": null
}
EOF
}

write_params_dual() {
  cat >"$1" <<EOF
{
  "node_name": "$RESI_NODE_NAME",
  "server": "$RESI_SERVER_IP",
  "sni": "$RESI_SNI",
  "protocol": "vless-reality",
  "uuid": "$RESI_UUID",
  "reality_public_key": "$RESI_REALITY_PUBLIC_KEY",
  "short_id": "$RESI_SHORT_ID",
  "port": $RESI_INBOUND_PORT,
  "alt_tcp_ports": [2096, 8880, 40443],
  "allow_quic": false,
  "hysteria2": {
    "enabled": true,
    "port": 443,
    "alt_ports": [2096, 8880],
    "password": "$RESI_HY2_PASSWORD",
    "obfs_password": "$RESI_HY2_OBFS_PASSWORD",
    "sni": "$RESI_SNI"
  },
  "cf_ws": {
    "enabled": true,
    "domain": "example.com",
    "path": "$RESI_CDN_WS_PATH",
    "port": 443,
    "uuid": "$RESI_UUID",
    "ips": ["203.0.113.20", "203.0.113.21"]
  },
  "dc": {
    "node_name": "$DC_NODE_NAME",
    "server": "$DC_SERVER_IP",
    "sni": "$DC_SNI",
    "protocol": "vless-reality",
    "uuid": "$DC_UUID",
    "reality_public_key": "$DC_REALITY_PUBLIC_KEY",
    "short_id": "$DC_SHORT_ID",
    "port": $DC_INBOUND_PORT,
    "alt_tcp_ports": [2096, 8880]
  }
}
EOF
}

main() {
  rm -rf "$EXAMPLES/single-node" "$EXAMPLES/dual-node"
  mkdir -p "$EXAMPLES/single-node" "$EXAMPLES/dual-node"

  # Rule-set stub. The real profile inlines ~460 KB of upstream domain and CIDR
  # rules; committing that would bury the structure the examples exist to show
  # and would churn on every upstream refresh. A three-entry stand-in keeps the
  # examples readable and deterministic.
  local stub
  stub="$(mktemp -d)"
  cat >"$stub/geosite-cn.json" <<'JSON'
{"version": 3, "rules": [{"domain_suffix": ["example-cn-site.cn", "example-cn-cdn.com"]}]}
JSON
  cat >"$stub/geoip-cn.json" <<'JSON'
{"version": 3, "rules": [{"ip_cidr": ["198.51.100.0/24"]}]}
JSON
  cat >"$stub/geosite-category-ads-all.json" <<'JSON'
{"version": 3, "rules": [{"domain_suffix": ["example-ad-network.example"]}]}
JSON

  # ── Single-node example ────────────────────────────────────────────
  declare_fakes_single

  # Server inbounds, one per path.
  render "$TEMPLATES/singbox/11_xtls-reality_inbounds.json.tmpl" \
    "$EXAMPLES/single-node/11_xtls-reality_inbounds.json"
  render "$TEMPLATES/singbox/11_anytls-reality_inbounds.json.tmpl" \
    "$EXAMPLES/single-node/11_anytls-reality_inbounds.json"
  HY2_PORT=443 HY2_SNI="$SNI" \
    HY2_CERT_PATH=/etc/anyreality-resi-stack/hy2-cert.pem \
    HY2_KEY_PATH=/etc/anyreality-resi-stack/hy2-key.pem \
    HY2_PASSWORD="$HY2_PASSWORD" HY2_OBFS_PASSWORD="$HY2_OBFS_PASSWORD" \
    render "$TEMPLATES/singbox/12_hysteria2_inbounds.json.tmpl" \
    "$EXAMPLES/single-node/12_hysteria2_inbounds.json"
  CDN_WS_PATH="$CDN_WS_PATH" \
    render "$TEMPLATES/singbox/13_vless-ws_inbounds.json.tmpl" \
    "$EXAMPLES/single-node/13_vless-ws_inbounds.json"

  cp "$TEMPLATES/singbox/00_log.json" "$EXAMPLES/single-node/00_log.json"
  cp "$TEMPLATES/singbox/01_outbounds.json" "$EXAMPLES/single-node/01_outbounds.json"
  cp "$TEMPLATES/singbox/03_route.json" "$EXAMPLES/single-node/03_route.json"
  cp "$TEMPLATES/singbox/05_dns.json" "$EXAMPLES/single-node/05_dns.json"
  cp "$TEMPLATES/singbox/06_ntp.json" "$EXAMPLES/single-node/06_ntp.json"

  render "$TEMPLATES/singbox-client/outbound.json.tmpl" \
    "$EXAMPLES/single-node/sing-box-client-outbound.json"
  render "$TEMPLATES/singbox-client/anytls-outbound.json.tmpl" \
    "$EXAMPLES/single-node/sing-box-client-anytls-outbound.json"

  # Client profiles come from the builder, never from a template: two
  # hand-maintained profiles for the same topology drift, and the drift is only
  # visible to whichever client family reads the file nobody re-checked.
  write_params_single "$stub/params-single.json"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-single.json" \
    --format singbox --rulesets "$stub" \
    --out "$EXAMPLES/single-node/sing-box-client-config.json"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-single.json" \
    --format clash --rulesets "$stub" \
    --out "$EXAMPLES/single-node/clash-profile.yaml"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-single.json" \
    --format uris \
    --out "$EXAMPLES/single-node/uris-profile.txt"

  cat >"$EXAMPLES/single-node/vless-link.txt" <<EOF
vless://${UUID}@${SERVER_IP}:${INBOUND_PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${SNI}&fp=chrome&pbk=${REALITY_PUBLIC_KEY}&sid=${SHORT_ID}&type=tcp#${NODE_NAME}
EOF

  # ── Dual-node example ──────────────────────────────────────────────
  declare_fakes_dual
  write_params_dual "$stub/params-dual.json"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-dual.json" \
    --format singbox --rulesets "$stub" \
    --out "$EXAMPLES/dual-node/sing-box-client-dual.json"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-dual.json" \
    --format clash --rulesets "$stub" \
    --out "$EXAMPLES/dual-node/clash-profile.yaml"
  "$REPO_ROOT/scripts/build_profile.py" --params "$stub/params-dual.json" \
    --format uris \
    --out "$EXAMPLES/dual-node/uris-profile.txt"

  cat >"$EXAMPLES/dual-node/vless-links.txt" <<EOF
vless://${RESI_UUID}@${RESI_SERVER_IP}:${RESI_INBOUND_PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${RESI_SNI}&fp=chrome&pbk=${RESI_REALITY_PUBLIC_KEY}&sid=${RESI_SHORT_ID}&type=tcp#${RESI_NODE_NAME}
vless://${DC_UUID}@${DC_SERVER_IP}:${DC_INBOUND_PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${DC_SNI}&fp=chrome&pbk=${DC_REALITY_PUBLIC_KEY}&sid=${DC_SHORT_ID}&type=tcp#${DC_NODE_NAME}
EOF

  rm -rf "$stub"

  # ── Example READMEs ────────────────────────────────────────────────
  cat >"$EXAMPLES/README.md" <<'EOF'
# examples/

Auto-generated by `scripts/make-example.sh`. Server inbounds come from
`templates/`; client profiles come from `scripts/build_profile.py`, the same
generator the installer runs — so an example can never disagree with what a
real install produces.

**All values are placeholders.** Specifically:
- UUIDs are all-zero / all-ones sentinels
- IPs are RFC 5737 documentation ranges (`203.0.113.0/24`, `198.51.100.0/24`)
- Reality public/private keys are sentinel `AAA…` / `BBB…` strings (NOT valid Curve25519 keys — these will not work as live credentials)
- Subscription token is the literal string `example-token-do-not-use`
- The inlined rule-sets are a three-entry stub. A real profile inlines the full
  upstream sets (~460 KB, ~79 KB gzipped); the structure is identical.

Do not deploy these. Use `install/install.sh` to generate real values for your VPS.

## Contents

`single-node/` — one VPS exposing three paths (see [CHINA-NETWORK](../docs/en/CHINA-NETWORK.md)):

| File | What it is |
|---|---|
| `11_xtls-reality_inbounds.json` | VLESS + Reality + Vision inbound (default protocol) |
| `11_anytls-reality_inbounds.json` | AnyTLS + Reality inbound (`--protocol anytls-reality`) |
| `12_hysteria2_inbounds.json` | Hysteria2 / UDP inbound |
| `13_vless-ws_inbounds.json` | VLESS + WebSocket inbound behind the CDN relay |
| `sing-box-client-config.json` | generated sing-box profile: every path, grouped, with inline rule-sets |
| `clash-profile.yaml` | the same topology for mihomo / Clash |
| `uris-profile.txt` | Base64-encoded URI bundle of all paths for Shadowrocket / v2rayN / v2rayNG / Streisand |
| `sing-box-client-outbound.json`, `sing-box-client-anytls-outbound.json` | single outbounds, for hand-assembled configs |
| `vless-link.txt` | share link for the direct REALITY path only (no failover) |

`dual-node/` — residential leaf + data-center aggregator, with Telegram and
Discord routed out of the data centre and everything else through the
residential exit.
EOF

  echo "examples/ regenerated."
}

main "$@"
