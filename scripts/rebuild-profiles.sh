#!/usr/bin/env bash
# rebuild-profiles.sh — regenerate the served client profiles from the params
# file, validate them, and only then publish.
#
# This is the single path that writes a profile. It exists because the failure
# it prevents is invisible: a hand-copied "static fallback" profile once sat
# unmaintained for a month while the authoritative one moved on. When the
# fallback finally kicked in, clients updated *successfully* and then could not
# connect to anything — worse than having no fallback, because it looked fine.
#
# Publish is atomic and validated: build into a temp dir, run
# scripts/check_profile.py, and swap in only on success. A failed rebuild
# leaves last week's working profile in place.
#
# Usage: rebuild-profiles.sh [--fetch]
#   --fetch   refresh the rule-set sources first (weekly timer passes this)

set -Eeuo pipefail

PREFIX=/etc/anyreality-resi-stack
STATE=/var/lib/anyreality-resi-stack
PARAMS="$PREFIX/profile-params.json"
FILE_DIR="$PREFIX/files"
RULESETS="$STATE/rulesets"
LIB=/usr/local/lib/anyreality-resi-stack

[[ -f "$PARAMS" ]] || {
  echo "rebuild-profiles: $PARAMS missing — was the installer run with a subscription?" >&2
  exit 1
}

if [[ "${1:-}" == "--fetch" ]]; then
  # Best effort. A failed refresh keeps the previous sources; it must not stop
  # the rebuild, and it must not publish a profile with no domestic rules.
  "$LIB/fetch-rulesets.sh" "$RULESETS" || echo "rebuild-profiles: rule-set refresh incomplete, using cached copies" >&2
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

formats=(singbox uris)
# The Clash profile only exists for protocols mihomo can actually express.
protocol="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("protocol",""))' "$PARAMS")"
if [[ "$protocol" != "anytls-reality" ]]; then
  formats+=(clash)
fi

for fmt in "${formats[@]}"; do
  out="$tmp/profile.json"
  [[ "$fmt" == "clash" ]] && out="$tmp/profile.yaml"
  [[ "$fmt" == "uris" ]] && out="$tmp/profile.txt"
  python3 "$LIB/build_profile.py" \
    --params "$PARAMS" --format "$fmt" --rulesets "$RULESETS" --out "$out"
done

check_args=("$tmp/profile.json")
[[ -f "$tmp/profile.yaml" ]] && check_args+=("$tmp/profile.yaml")
[[ -f "$tmp/profile.txt" ]] && check_args+=("$tmp/profile.txt")
if ! python3 "$LIB/check_profile.py" "${check_args[@]}"; then
  echo "rebuild-profiles: refusing to publish — invariants violated (see above)" >&2
  exit 1
fi

# A profile that passes the structural checks can still be rejected by the
# kernel that has to run it. Catch that here rather than on the user's phone.
if command -v sing-box >/dev/null 2>&1; then
  if ! sing-box check -c "$tmp/profile.json" >/dev/null 2>&1; then
    echo "rebuild-profiles: sing-box rejected the generated profile — not publishing" >&2
    sing-box check -c "$tmp/profile.json" >&2 || true
    exit 1
  fi
fi

install -d -m 0755 "$FILE_DIR"
for file in profile.json profile.yaml profile.txt; do
  [[ -f "$tmp/$file" ]] || continue
  install -m 0644 "$tmp/$file" "$FILE_DIR/$file"
done

echo "rebuild-profiles: published $(cd "$tmp" && ls profile.* | tr '\n' ' ')to $FILE_DIR"
