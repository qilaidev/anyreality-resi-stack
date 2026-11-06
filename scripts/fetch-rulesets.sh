#!/usr/bin/env bash
# fetch-rulesets.sh — refresh the routing rule-set *sources* on the server.
#
# The client profile inlines these rules (see scripts/build_profile.py). That
# is deliberate: a `type: remote` rule-set is downloaded by sing-box *during
# startup*, and any failure is FATAL. On a jittery domestic line the same three
# files went from 0.6 s to "8 KB times out after 10 s" within minutes, so the
# first import of a profile would kill the client with no visible cause.
#
# Moving the download to the server changes who pays for the flakiness: the
# server has a clean uplink, downloads on a weekly timer, and on failure simply
# keeps last week's copy. A client boot never touches the network.
#
# Never writes a partial file: download to a temp file, verify it parses, then
# atomically install.
#
# Usage: fetch-rulesets.sh [DEST_DIR]   (default /var/lib/anyreality-resi-stack/rulesets)

set -Eeuo pipefail

DEST="${1:-/var/lib/anyreality-resi-stack/rulesets}"
mkdir -p "$DEST"

# Primary source: SagerNet's compiled .srs, decompiled locally with sing-box.
# Fallback: a mirror that publishes sing-box *source* JSON directly, for hosts
# where sing-box is somehow not on PATH.
#
# The order is not arbitrary. Both sources cover the same job, and measured on
# the same host:
#
#   geosite-cn                SagerNet    9,131 entries / 223 KiB
#                             mirror    111,305 entries / 1703 KiB
#   geoip-cn                  SagerNet    7,876 entries / 204 KiB
#   geosite-category-ads-all  SagerNet      890 entries /  25 KiB
#
# The mirror flattens every attribute variant of the CN set, which is 12x the
# size for no additional coverage of what this profile routes. Since the rules
# are inlined into a profile that phones re-download on a bad line, that
# difference is the whole subscription: ~450 KiB of rules instead of ~1.8 MiB.
SAGER_SITE="https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set"
SAGER_IP="https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set"
MIRROR_BASE="https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing/geo"

# tag|srs-url|fallback-json-url
SOURCES=(
  "geosite-cn|$SAGER_SITE/geosite-cn.srs|$MIRROR_BASE/geosite/cn.json"
  "geoip-cn|$SAGER_IP/geoip-cn.srs|$MIRROR_BASE/geoip/cn.json"
  "geosite-category-ads-all|$SAGER_SITE/geosite-category-ads-all.srs|$MIRROR_BASE/geosite/category-ads-all.json"
)

ok=0
fail=0

# json_has_rules FILE — a 200 response is not proof of a usable rule-set; a
# rate-limit page or an HTML error also arrives with status 200 from some
# mirrors. Require it to parse and to carry at least one rule.
json_has_rules() {
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    sys.exit(1)
rules = data.get("rules")
sys.exit(0 if isinstance(rules, list) and rules else 1)
PY
}

for entry in "${SOURCES[@]}"; do
  IFS='|' read -r tag srs_url json_url <<<"$entry"
  tmp="$(mktemp)"
  got=0

  if command -v sing-box >/dev/null 2>&1; then
    # `sing-box rule-set decompile` writes <name>.json next to its input, so
    # work inside a scratch dir.
    scratch="$(mktemp -d)"
    if curl -fsSL --max-time 60 "$srs_url" -o "$scratch/$tag.srs" &&
      sing-box rule-set decompile "$scratch/$tag.srs" >/dev/null 2>&1 &&
      json_has_rules "$scratch/$tag.json"; then
      cp "$scratch/$tag.json" "$tmp"
      got=1
    fi
    rm -rf "$scratch"
  fi

  if [[ "$got" != "1" ]] && curl -fsSL --max-time 60 "$json_url" -o "$tmp" &&
    json_has_rules "$tmp"; then
    echo "note  $tag came from the fallback mirror — expect a larger profile" >&2
    got=1
  fi

  if [[ "$got" == "1" ]]; then
    install -m 0644 "$tmp" "$DEST/$tag.json"
    ok=$((ok + 1))
    echo "ok    $tag -> $DEST/$tag.json"
  else
    fail=$((fail + 1))
    if [[ -f "$DEST/$tag.json" ]]; then
      echo "keep  $tag (download failed, previous copy retained)" >&2
    else
      echo "MISS  $tag (download failed and no previous copy)" >&2
    fi
  fi
  rm -f "$tmp"
done

echo "fetch-rulesets: ok=$ok fail=$fail dest=$DEST"
((fail == 0))
