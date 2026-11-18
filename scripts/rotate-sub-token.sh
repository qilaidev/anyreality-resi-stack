#!/usr/bin/env bash
# rotate-sub-token.sh — rotate the subscription token on an installed node.
#
# The subscription URL is a credential: it is served over plain HTTP and the
# profile behind it contains the node password. If that URL leaks (shared
# screenshot, a client that syncs profiles to a third party, a stolen laptop),
# the only remedy is a new token. Before this script that meant reinstalling.
#
# Installed by the installer as:
#   /usr/local/sbin/anyreality-resi-stack-rotate-sub-token
#
# Usage:
#   anyreality-resi-stack-rotate-sub-token [--dry-run]
#
# After rotation EVERY client must re-import the new URL — the old one 404s.
# If another host runs the aggregator against this leaf, update its
# REMOTE_STATUS_URL too or its usage card will freeze on the cached value.

set -Eeuo pipefail

ETC_DIR=/etc/anyreality-resi-stack
SECRETS="$ETC_DIR/secrets.env"

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h | --help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

[[ "${EUID:-$(id -u)}" -eq 0 ]] || {
  echo "Run as root (sudo)." >&2
  exit 1
}
[[ -f "$SECRETS" ]] || {
  echo "$SECRETS not found — is this an anyreality-resi-stack node?" >&2
  exit 1
}

unit=""
for candidate in subscription-leaf subscription-aggregator; do
  [[ -f "/etc/systemd/system/${candidate}.service" ]] && unit="$candidate"
done
[[ -n "$unit" ]] || {
  echo "No subscription service installed — nothing to rotate." >&2
  exit 1
}

ENV_FILE="$ETC_DIR/${unit}.env"
[[ -f "$ENV_FILE" ]] || {
  echo "$ENV_FILE not found." >&2
  exit 1
}

new_token="$(uuidgen)"
old_token="$(awk -F= '/^SUB_TOKEN=/ {print $2}' "$SECRETS" | tail -1)"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry] unit         : $unit"
  echo "[dry] env file     : $ENV_FILE"
  echo "[dry] old token    : ${old_token:0:8}…"
  echo "[dry] new token    : ${new_token:0:8}…"
  echo "[dry] would rewrite SUB_TOKEN in $SECRETS and TOKEN in $ENV_FILE, then restart $unit"
  exit 0
fi

# Keep a one-generation rollback copy of both files before touching them.
cp -a "$SECRETS" "${SECRETS}.bak"
cp -a "$ENV_FILE" "${ENV_FILE}.bak"

rewrite_kv() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp)"
  chmod --reference="$file" "$tmp"
  if grep -q "^${key}=" "$file"; then
    sed "s|^${key}=.*|${key}=${value}|" "$file" >"$tmp"
  else
    cat "$file" >"$tmp"
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  mv "$tmp" "$file"
}

rewrite_kv "$SECRETS" SUB_TOKEN "$new_token"
rewrite_kv "$ENV_FILE" TOKEN "$new_token"

systemctl restart "$unit"

port="$(awk -F= '/^PORT=/ {print $2}' "$ENV_FILE" | tail -1)"
port="${port:-80}"
# With TLS on, the certificate is for a hostname while we probe loopback, so -k
# is correct: this verifies the service came back, not certificate trust.
scheme="http"
curl_opts=(-fsS --max-time 3)
if grep -q '^TLS_CERT_FILE=.' "$ENV_FILE"; then
  scheme="https"
  curl_opts+=(-k)
fi
base="${scheme}://127.0.0.1:${port}"

ok=0
for _ in 1 2 3 4 5; do
  if curl "${curl_opts[@]}" "${base}/healthz" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "$ok" != "1" ]]; then
  echo "Service did not come back healthy — rolling back." >&2
  mv "${SECRETS}.bak" "$SECRETS"
  mv "${ENV_FILE}.bak" "$ENV_FILE"
  systemctl restart "$unit"
  echo "Rolled back to the previous token. Check: journalctl -u $unit -n 50" >&2
  exit 1
fi

# Verify the new path actually serves the profile before declaring success.
if ! curl "${curl_opts[@]}" -o /dev/null "${base}/${new_token}/"; then
  echo "WARNING: /healthz is up but the new token path did not return a profile." >&2
  echo "         Check FILE_DIR / DEFAULT_TARGET in $ENV_FILE." >&2
fi

rm -f "${SECRETS}.bak" "${ENV_FILE}.bak"

server_ip="$(awk -F= '/^SERVER_IP=/ {print $2}' "$SECRETS" 2>/dev/null | tail -1)"
server_ip="${server_ip:-$(curl -fsS --max-time 5 https://checkip.amazonaws.com 2>/dev/null || echo "<server-ip>")}"

echo
echo "Subscription token rotated for $unit."
if [[ "$scheme" == "https" ]]; then
  echo "New URL: https://<your-cert-hostname>:${port}/${new_token}/"
  echo "         (use the hostname the certificate was issued for, not the IP)"
else
  echo "New URL: http://${server_ip}:${port}/${new_token}/"
fi
echo
echo "Next steps:"
echo "  1. Re-import this URL in every client — the old URL now returns 404."
echo "  2. If an aggregator node polls this host, update its REMOTE_STATUS_URL."
if [[ "$scheme" != "https" ]]; then
  echo "  3. Treat this URL as a password: it is served over plain HTTP."
fi
