#!/usr/bin/env bash
# common.sh — shared helpers for anyreality-resi-stack installer modules.
# Sourced by install.sh and other lib/*.sh files. Targets Ubuntu/Debian
# (bash 4+, GNU coreutils). Not meant to be executed directly.

# ── Color & logging ──────────────────────────────────────────────────────
C_RESET=$'\033[0m'
C_CYAN=$'\033[1;36m'
C_GREEN=$'\033[1;32m'
C_YELLOW=$'\033[1;33m'
C_RED=$'\033[1;31m'
C_GRAY=$'\033[0;90m'

step() { printf "\n%s>> %s%s\n" "$C_CYAN" "$*" "$C_RESET"; }
ok() { printf "%s   ✔ %s%s\n" "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf "%s   ⚠ %s%s\n" "$C_YELLOW" "$*" "$C_RESET"; }
fail() { printf "%s   ✘ %s%s\n" "$C_RED" "$*" "$C_RESET" >&2; }
info() { printf "%s   %s%s\n" "$C_GRAY" "$*" "$C_RESET"; }

die() {
  fail "$*"
  exit 1
}

# Where the installer puts the tools that must be available on the box itself
# (profile builder, validators, rule-set refresher) rather than only in a
# checkout. One definition: three modules used to carry their own copy.
# shellcheck disable=SC2034  # consumed by system.sh and subscription.sh
LIB_DIR=/usr/local/lib/anyreality-resi-stack

# ── Privilege / environment ──────────────────────────────────────────────
require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run as root (e.g. sudo bash $0)"
  fi
}

# ── Dry-run wrapper ──────────────────────────────────────────────────────
# Set DRY_RUN=1 to print commands instead of executing them. Use `run` for
# every side-effecting command (apt, systemctl, sed -i, mkdir, etc).
DRY_RUN="${DRY_RUN:-0}"

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf "%s[dry] %s%s\n" "$C_GRAY" "$*" "$C_RESET"
    return 0
  fi
  "$@"
}

# write_file <path> <mode>  — read content from stdin, write atomically.
# Honors DRY_RUN.
write_file() {
  local path="$1" mode="$2"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf "%s[dry] write %s (mode %s):%s\n" "$C_GRAY" "$path" "$mode" "$C_RESET"
    sed 's/^/[dry]   /' >&2
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp"
  chmod "$mode" "$tmp"
  mv "$tmp" "$path"
}

# ── Retry ────────────────────────────────────────────────────────────────
retry() {
  local tries="$1" delay="$2"
  shift 2
  local n=0
  until "$@"; do
    n=$((n + 1))
    if ((n >= tries)); then
      fail "command failed after $n attempts: $*"
      return 1
    fi
    warn "retry $n/$tries in ${delay}s: $*"
    sleep "$delay"
  done
}

# ── Template rendering ───────────────────────────────────────────────────
# render_template <template-file> <output-file> [mode]
# Replaces every @@VAR@@ token with the value of $VAR from the environment.
# Uses python3 for safe string replacement (no shell expansion, no eval).
# All @@VAR@@ tokens must have a corresponding env var or the call dies.
#
# The character class MUST include digits. It used to be `[A-Z_]+`, which does
# not match `@@HY2_PASSWORD@@` — so every Hysteria2 token was silently skipped:
# not validated, not substituted, and the render reported success with the
# tokens still in the file. Only `sing-box check` caught it, a phase later.
# The post-render assertion at the bottom is the belt to that braces: whatever
# the pattern misses, a leftover token in the output is now a hard failure.
render_template() {
  local in="$1" out="$2" mode="${3:-0644}"
  [[ -f "$in" ]] || die "render_template: template not found: $in"

  local vars token name
  vars="$(grep -oE '@@[A-Z0-9_]+@@' "$in" 2>/dev/null | sort -u || true)"

  for token in $vars; do
    name="${token//@/}"
    if [[ -z "${!name+x}" ]]; then
      die "render_template: variable '$name' required by $in is unset"
    fi
  done

  if [[ "$DRY_RUN" == "1" ]]; then
    printf "%s[dry] render %s -> %s%s\n" "$C_GRAY" "$in" "$out" "$C_RESET"
    return 0
  fi

  mkdir -p "$(dirname "$out")"
  python3 - "$in" "$out" "$vars" <<'PY'
import os, sys, pathlib
src, dst, vars_line = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(src).read_text()
for tok in vars_line.split():
    name = tok.strip('@')
    val = os.environ.get(name)
    if val is None:
        sys.stderr.write(f"render_template: missing env var {name}\n")
        sys.exit(1)
    text = text.replace(tok, val)
pathlib.Path(dst).write_text(text)
PY
  chmod "$mode" "$out"

  # Verify the output, not the substitution logic. A leftover token here means a
  # placeholder reached a live config file, where it surfaces much later and
  # much less clearly than this line does.
  local leftover
  leftover="$(grep -oE '@@[A-Za-z0-9_]+@@' "$out" 2>/dev/null | sort -u | tr '\n' ' ' || true)"
  if [[ -n "$leftover" ]]; then
    die "render_template: $out still contains unsubstituted token(s): $leftover
The placeholder was not recognised. Check the token spelling against the
pattern above, and make sure the variable is exported."
  fi
}

# ── Idempotency helpers ──────────────────────────────────────────────────
# ensure_line <line> <file> — append line if missing.
ensure_line() {
  local line="$1" file="$2"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf "%s[dry] ensure_line in %s: %s%s\n" "$C_GRAY" "$file" "$line" "$C_RESET"
    return 0
  fi
  mkdir -p "$(dirname "$file")"
  touch "$file"
  grep -qF -- "$line" "$file" || printf '%s\n' "$line" >>"$file"
}

# pkg_installed <name>
pkg_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

# ── Service helpers ──────────────────────────────────────────────────────
svc_enable_now() {
  local name="$1"
  run systemctl daemon-reload
  run systemctl enable --now "$name"
}

svc_restart() {
  local name="$1"
  run systemctl restart "$name"
}

svc_is_active() {
  systemctl is-active --quiet "$1"
}

# ── Network ──────────────────────────────────────────────────────────────
# default_interface — print the primary outbound interface name.
default_interface() {
  ip -o route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="dev") print $(i+1)}' | head -1
}

# port_in_use <port>
port_in_use() {
  ss -tlnH "sport = :$1" 2>/dev/null | grep -q .
}
