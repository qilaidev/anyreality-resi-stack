#!/usr/bin/env bash
# redact.sh — scan tree for known-leaked credentials and high-entropy secret shapes.
# Exits non-zero on any hit. Designed for CI gates and local pre-commit hooks.
# Portable: works on macOS bash 3.2 and Linux bash 4+.
#
# Three checks:
#   1. SHA-256 denylist (.redact-denylist.sha256) — exact-match known leaks.
#   2. Suspicious filename patterns (.env, *.key, *.pem, *.tar.gz, etc).
#   3. Suspicious string shapes (UUID, 43-char base64url for Reality keys) NOT in
#      the placeholder allowlist.
#
# Usage: scripts/redact.sh [path...]   (defaults to repo root)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DENYLIST="$SCRIPT_DIR/.redact-denylist.sha256"

# Placeholder allowlist — values we ship intentionally in templates/examples.
ALLOWLIST_PLAINTEXT=(
  "00000000-0000-0000-0000-000000000000"
  "11111111-1111-1111-1111-111111111111"
  "REPLACE_UUID"
  "REPLACE_PRIVATE_KEY"
  "REPLACE_PUBLIC_KEY"
  "REPLACE_SUB_TOKEN"
  "example-token-do-not-use"
  "example-anytls-password-do-not-use"
  "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
)

# Filenames that must never enter the repo.
FORBIDDEN_FILENAMES=(
  "secrets.env"
  "usage-state.json"
  "usage-cache.json"
)
FORBIDDEN_GLOBS=(
  "*.key"
  "*.pem"
  "*.tar.gz"
  "*.tar"
  "*.zip"
  "*.7z"
)

# Files exempt from shape-based scanning (themselves contain regexes about secrets,
# or are Base64-encoded bundles generated from the placeholder allowlist).
EXEMPT_FILES=(
  "scripts/redact.sh"
  "scripts/.redact-denylist.sha256"
  "examples/single-node/uris-profile.txt"
  "examples/dual-node/uris-profile.txt"
)

C_RED=$'\033[1;31m'
C_GREEN=$'\033[1;32m'
C_YELLOW=$'\033[1;33m'
C_RESET=$'\033[0m'

fail_count=0
fail() {
  printf "%s[FAIL]%s %s\n" "$C_RED" "$C_RESET" "$*" >&2
  fail_count=$((fail_count + 1))
}
warn() { printf "%s[WARN]%s %s\n" "$C_YELLOW" "$C_RESET" "$*" >&2; }
ok() { printf "%s[OK]%s   %s\n" "$C_GREEN" "$C_RESET" "$*"; }
info() { printf "%s\n" "$*"; }

if [[ $# -gt 0 ]]; then
  SCAN_ROOTS=("$@")
else
  SCAN_ROOTS=("$REPO_ROOT")
fi

# SHA-256 helper (portable: shasum on macOS, sha256sum on Linux).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

# Pre-compute allowlist hashes once.
ALLOWLIST_HASHES=()
for a in "${ALLOWLIST_PLAINTEXT[@]}"; do
  ALLOWLIST_HASHES+=("$(sha256_of "$a")")
done

is_allowlisted_hash() {
  local h="$1" a
  for a in "${ALLOWLIST_HASHES[@]}"; do
    [[ "$a" == "$h" ]] && return 0
  done
  return 1
}

# Load denylist (portable read loop, bash 3.2 compatible).
DENY_HASHES=()
while IFS= read -r line; do
  case "$line" in
    '' | \#*) continue ;;
  esac
  hash="$(printf '%s' "$line" | awk '{print $1}')"
  [[ -n "$hash" ]] && DENY_HASHES+=("$hash")
done <"$DENYLIST"

if [[ ${#DENY_HASHES[@]} -eq 0 ]]; then
  warn "Denylist is empty: $DENYLIST"
fi

is_denied_hash() {
  local h="$1" d
  for d in "${DENY_HASHES[@]}"; do
    [[ "$d" == "$h" ]] && return 0
  done
  return 1
}

is_exempt_file() {
  local rel="${1#"$REPO_ROOT"/}" e
  for e in "${EXEMPT_FILES[@]}"; do
    [[ "$rel" == "$e" ]] && return 0
  done
  return 1
}

# Build find args for skip dirs.
# Collect files (portable, NUL-safe).
# The -prune list below is the single source of truth for skipped directories;
# keep it inline — building find args dynamically is not worth the quoting risk.
FILES=()
for root in "${SCAN_ROOTS[@]}"; do
  if [[ -f "$root" ]]; then
    FILES+=("$root")
    continue
  fi
  while IFS= read -r -d '' f; do
    FILES+=("$f")
  done < <(
    find "$root" \
      \( -name .git -o -name node_modules -o -name _site \
      -o -name .jekyll-cache -o -name __pycache__ \
      -o -name .pytest_cache -o -name .ruff_cache -o -name vendor \) -prune \
      -o -type f -print0
  )
done

info "Scanning ${#FILES[@]} files…"

# Check 1: forbidden filenames / globs.
for f in "${FILES[@]}"; do
  base="$(basename "$f")"
  for fn in "${FORBIDDEN_FILENAMES[@]}"; do
    [[ "$base" == "$fn" ]] && fail "Forbidden filename: $f"
  done
  for g in "${FORBIDDEN_GLOBS[@]}"; do
    # shellcheck disable=SC2053
    [[ "$base" == $g ]] && fail "Forbidden file pattern ($g): $f"
  done
done

# Regex shapes.
UUID_RE='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
B64URL43_RE='[A-Za-z0-9_-]{43}'
IPV4_RE='([0-9]{1,3}\.){3}[0-9]{1,3}'

# The 43-char base64url shape also matches any long snake_case identifier, so
# descriptive function and test names kept tripping the scanner — which trains
# people to rename good code or pad the allowlist with non-secrets. Exclude
# single-case snake_case instead: a Reality key is 43 random base64url chars,
# so the odds it lands entirely in [a-z0-9_] (or entirely in [A-Z0-9_]) with
# well-formed underscores are about 2e-10. Mixed case is still scanned.
#
# kebab-case needs the same exemption, and for the same reason: Markdown
# heading anchors (e.g. '#protocol-choice-anyreality-default-vs-vless') are
# lowercase-and-hyphens and occasionally land on exactly 43 characters. Since
# 2026-08-03 that produced 8 permanent violations on main, so the redact CI job
# had been red for days — which is worse than no check at all, because a real
# leak would now scroll past in a wall of known-bad output. Odds a random
# base64url key falls entirely in [a-z0-9-] with well-formed hyphens are
# ~1e-10, the same order as the snake_case carve-out above.
is_source_identifier() {
  local s="$1"
  [[ "$s" =~ ^_?[a-z0-9]+(_[a-z0-9]+)+_?$ ]] && return 0
  [[ "$s" =~ ^_?[A-Z0-9]+(_[A-Z0-9]+)+_?$ ]] && return 0
  [[ "$s" =~ ^-?[a-z0-9]+(-+[a-z0-9]+)+-?$ ]] && return 0
  return 1
}

for f in "${FILES[@]}"; do
  # Skip binary files.
  if ! grep -Iq . "$f" 2>/dev/null; then continue; fi

  # Always check denylist (even for exempt files).
  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    h="$(sha256_of "$candidate")"
    if is_denied_hash "$h"; then
      fail "Known-leaked secret in $f: matches denylist hash $h"
    fi
  done < <(grep -Eoh "$UUID_RE|$B64URL43_RE" "$f" 2>/dev/null | sort -u)

  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    h="$(sha256_of "$candidate")"
    if is_denied_hash "$h"; then
      fail "Known-leaked IP in $f: $candidate (hash $h)"
    fi
  done < <(grep -Eoh "$IPV4_RE" "$f" 2>/dev/null | sort -u)

  # Shape check skipped for exempt files.
  if is_exempt_file "$f"; then continue; fi

  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if is_source_identifier "$candidate"; then continue; fi
    h="$(sha256_of "$candidate")"
    if is_allowlisted_hash "$h"; then continue; fi
    fail "Unknown secret-shape string in $f: '$candidate' (hash $h) — add to allowlist or remove."
  done < <(grep -Eoh "$UUID_RE|$B64URL43_RE" "$f" 2>/dev/null | sort -u)
done

if [[ "$fail_count" -gt 0 ]]; then
  printf "\n%sredact: %d violation(s)%s\n" "$C_RED" "$fail_count" "$C_RESET" >&2
  exit 1
fi

ok "redact: clean (${#FILES[@]} files scanned, ${#DENY_HASHES[@]} denylist entries)"
