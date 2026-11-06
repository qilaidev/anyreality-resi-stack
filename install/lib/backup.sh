#!/usr/bin/env bash
# backup.sh — install a daily systemd timer that tarballs configuration
# (NOT logs, NOT runtime state). It includes /etc/anyreality-resi-stack for
# rollback, so backup archives are sensitive and must not be shared publicly.

# shellcheck source=./common.sh
[[ -n "${COMMON_SH_LOADED:-}" ]] || {
  echo "backup.sh: source common.sh first" >&2
  exit 1
}

phase_backup() {
  step "Installing daily config backup timer"

  write_file /usr/local/sbin/backup-anyreality-resi-stack.sh 0755 <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_DIR=/var/backups/anyreality-resi-stack
STAMP="$(date +%Y-%m-%d-%H%M%S)"
OUT="$BACKUP_DIR/anyreality-resi-stack-${STAMP}.tar.gz"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
{
  echo "created_at=$(date -Is)"
  echo "hostname=$(hostname)"
  echo "kernel=$(uname -r)"
  echo "timezone=$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  systemctl show sing-box -p ActiveState -p SubState -p NRestarts 2>/dev/null || true
  ufw status verbose 2>/dev/null || true
  ss -tlnp 2>/dev/null || true
} > "$TMP/manifest.txt"

tar -czf "$OUT" -C / --ignore-failed-read \
  --exclude=var/lib/anyreality-resi-stack/usage-state.json \
  --exclude=var/lib/anyreality-resi-stack/usage-cache.json \
  --exclude='var/lib/anyreality-resi-stack/*.tmp' \
  --exclude='var/lib/anyreality-resi-stack/.*.tmp' \
  --exclude='etc/sing-box/logs' \
  --exclude='etc/sing-box/logs/*' \
  etc/sing-box \
  etc/systemd/system/sing-box.service \
  etc/systemd/system/subscription-leaf.service \
  etc/systemd/system/subscription-aggregator.service \
  etc/anyreality-resi-stack \
  usr/local/lib/anyreality-resi-stack \
  var/lib/anyreality-resi-stack \
  etc/ufw \
  etc/fail2ban \
  etc/sysctl.d \
  etc/systemd/journald.conf.d \
  -C "$TMP" manifest.txt
chmod 600 "$OUT"

# A backup nobody can read is worse than no backup, because it is trusted.
# Verify the archive is listable and actually carries the two things a restore
# depends on: the sing-box config and the secrets directory. Fail loudly (and
# drop the bad archive) rather than silently rotating a good one out for it.
# List once into a file: `tar | grep -q` would SIGPIPE tar on the first match
# and, under `set -o pipefail`, report a good archive as broken.
LISTING="$TMP/listing.txt"
if ! tar -tzf "$OUT" >"$LISTING" 2>/dev/null; then
  rm -f "$OUT"
  echo "backup verification failed: $OUT is not a readable gzip archive" >&2
  exit 1
fi
for required in etc/sing-box/conf/ etc/anyreality-resi-stack/; do
  if ! grep -q "^${required}" "$LISTING"; then
    rm -f "$OUT"
    echo "backup verification failed: $required missing from archive" >&2
    exit 1
  fi
done

# Off-box copy. Archives live on the same disk as the system, so they protect
# against a bad config — not against losing the VPS. Drop an executable script
# into the hook directory (rclone, scp, restic, whatever you already use) and it
# receives the verified archive path as $1. A failing hook fails the backup run,
# because a copy you believe exists but does not is the dangerous case.
HOOK_DIR=/etc/anyreality-resi-stack/backup-hooks.d
hook_failures=0
if [[ -d "$HOOK_DIR" ]]; then
  for hook in "$HOOK_DIR"/*; do
    [[ -f "$hook" && -x "$hook" ]] || continue
    if "$hook" "$OUT"; then
      echo "backup hook ok: $hook"
    else
      echo "backup hook FAILED: $hook" >&2
      hook_failures=$((hook_failures + 1))
    fi
  done
fi

# Retain only the 3 most recent VERIFIED backups.
find "$BACKUP_DIR" -name 'anyreality-resi-stack-*.tar.gz' -type f \
  | sort | head -n -3 | xargs -r rm -f

echo "$OUT"

if ((hook_failures > 0)); then
  echo "$hook_failures backup hook(s) failed — the local archive was kept" >&2
  exit 1
fi
EOF

  # Ship a disabled example so the hook contract is discoverable on the box
  # itself. Not executable, so it never runs until an operator opts in.
  write_file /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh.example 0644 <<'EOF'
#!/usr/bin/env bash
# Off-box backup hook. Copy to 10-offsite.sh, edit, then: chmod +x 10-offsite.sh
#
# $1 is the verified archive path. Exit non-zero to fail the backup run, which
# makes anyreality-resi-stack-healthcheck report a FAIL.
#
# The archive contains secrets and the subscription token — send it somewhere
# private and encrypted at rest.
set -Eeuo pipefail
ARCHIVE="$1"

# Example: rclone to any configured remote
# rclone copy "$ARCHIVE" myremote:anyreality-backups/ --config /root/.config/rclone/rclone.conf

# Example: scp to another host you control
# scp -i /root/.ssh/backup_key -o StrictHostKeyChecking=yes \
#   "$ARCHIVE" backup@backup.example.com:/srv/anyreality/

echo "configure an off-box destination in $0 (would have shipped $ARCHIVE)" >&2
exit 1
EOF

  run cp "$REPO_ROOT/templates/systemd/config-backup.service" \
    /etc/systemd/system/anyreality-resi-stack-backup.service
  run cp "$REPO_ROOT/templates/systemd/config-backup.timer" \
    /etc/systemd/system/anyreality-resi-stack-backup.timer
  run systemctl daemon-reload
  run systemctl enable --now anyreality-resi-stack-backup.timer
  ok "Backup timer installed"
}
