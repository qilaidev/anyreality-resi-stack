# Operations runbook

For a node that is already installed and needs to keep running. Walk through section 1 before you go live; after that you mostly need the health check in section 2 and the restore drill in section 4.

The installer places two operator tools on the server itself, so you do not need a repo checkout during an incident:

| Command | Purpose |
|---|---|
| `/usr/local/sbin/anyreality-resi-stack-healthcheck` | Read-only health check; safe to run any time, changes nothing |
| `/usr/local/sbin/anyreality-resi-stack-rotate-sub-token` | Rotate the subscription token (damage control for a leaked URL) |

Sections 1–6 cover day-to-day operation; section 7 turns on HTTPS, and section 8 lists what this stack deliberately does not do.

---

## 1. Pre-launch checklist

After installing, and before you hand the subscription URL to anyone:

```bash
# Catches most problems in one shot
anyreality-resi-stack-healthcheck
```

It must come back all green. Beyond that, confirm by hand:

- [ ] **Credentials are saved off-box.** `/etc/anyreality-resi-stack/secrets.env` (mode 600) holds `ANYTLS_PASSWORD` / `UUID` and the Reality keypair. Lose it and the only path forward is a reinstall, which invalidates every imported client.
- [ ] **You verified SSH still works from a second session**, especially after `--harden-ssh` or a changed `--ssh-port`. UFW does allow whatever port sshd is really bound to, but verify it yourself.
- [ ] **A real client connects.** Import the subscription on at least one device and check `https://ipinfo.io` through the node returns the expected residential IP. The installer's `phase_verify` only proves the local TLS handshake works; it cannot prove the path from a client is usable.
- [ ] **Treat the subscription URL as a password.** On plain HTTP the profile behind it — including the node password — is readable by anyone on the path. If you own a domain, enable TLS (section 7). Either way, keep the URL out of group chats, issues, and screenshots.
- [ ] **`FILE_DIR` (`/etc/anyreality-resi-stack/files`) contains profiles only.** Everything in that directory is served under the same token path — never put backups or notes there.
- [ ] **Clock is synchronised**: `timedatectl show -p NTPSynchronized --value` must print `yes`. A drifting clock makes Reality handshakes fail in a way that looks exactly like blocking.
- [ ] **Disk has headroom**: `df -h /`. Below 20% free, clean up before going live.

---

## 2. Health checks and alerting

```bash
anyreality-resi-stack-healthcheck          # full human-readable report
anyreality-resi-stack-healthcheck --quiet  # prints only problems (for cron)
```

Exit codes: `0` healthy (warnings may still print), `1` at least one FAIL — the node is degraded or down.

Covered: sing-box service state and restart count, whether the config still passes `sing-box check`, the inbound port actually listening, the subscription service and `/healthz` (over HTTPS when TLS is on), TLS certificate expiry, the profile file existing, backup freshness and failure state, whether an off-box backup hook is configured, root filesystem usage, `box.log` size, clock sync, UFW state, and `secrets.env` permissions.

**The cheapest alerting is cron**: cron mails you on any output, and `--quiet` prints nothing while healthy.

```bash
sudo crontab -e
# add:
*/10 * * * * /usr/local/sbin/anyreality-resi-stack-healthcheck --quiet
```

To push to a phone (Telegram / Bark / etc.), wrap it:

```bash
sudo tee /usr/local/sbin/anyreality-alert.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
out="$(/usr/local/sbin/anyreality-resi-stack-healthcheck --quiet 2>&1)" && exit 0
curl -fsS --max-time 10 -X POST \
  "https://api.telegram.org/bot<BOT_TOKEN>/sendMessage" \
  -d chat_id="<CHAT_ID>" \
  --data-urlencode "text=[$(hostname)] anyreality health check failed:
$out" >/dev/null
EOF
sudo chmod 700 /usr/local/sbin/anyreality-alert.sh
```

Then point the crontab line at `anyreality-alert.sh`.

### Manual triage

```bash
systemctl status sing-box
journalctl -u sing-box -n 100 --no-pager
journalctl -u subscription-leaf -n 100 --no-pager
sing-box check -C /etc/sing-box/conf
ss -tlnp | grep sing-box
```

---

## 3. Logs and disk

Three log sinks, all bounded — but worth knowing where the bounds are:

| Source | Location | Cap |
|---|---|---|
| systemd journal | journald | `SystemMaxUse=100M`, 14-day retention (`/etc/systemd/journald.conf.d/99-limits.conf`) |
| sing-box | `/etc/sing-box/logs/box.log` | logrotate: daily, immediate rotation past 20 MiB, 7 compressed generations (`/etc/logrotate.d/sing-box`) |
| Subscription servers | journald | as above |

sing-box runs at `level=error`, so `box.log` barely grows in normal operation. If the health check starts warning about its size, something is erroring continuously — read the log rather than just deleting it.

Verify the policy without rotating anything:

```bash
sudo logrotate -d /etc/logrotate.d/sing-box
```

---

## 4. Backups, verification, and restore drills

`anyreality-resi-stack-backup.timer` runs daily and writes to `/var/backups/anyreality-resi-stack/`, keeping the 3 most recent archives.

Archives **include**: `/etc/sing-box` (excluding `logs/`), the three systemd units, `/etc/anyreality-resi-stack` (secrets and tokens), `/usr/local/lib/anyreality-resi-stack`, `/var/lib/anyreality-resi-stack`, `/etc/ufw`, `/etc/fail2ban`, `/etc/sysctl.d`, and the journald drop-in.
They **exclude**: `usage-state.json` / `usage-cache.json` (runtime counters) and sing-box logs.

The backup script self-verifies after writing: the archive must list cleanly under `tar -tzf` and must actually contain `etc/sing-box/conf/` and `etc/anyreality-resi-stack/`. If either check fails the bad archive is deleted and the script exits non-zero (which the health check reports as a FAIL). This prevents the worst case — rotating a good backup out in favour of one that cannot be opened.

> ⚠️ Archives contain secrets and tokens, are mode 600, and must not be shared.

### Off-box copies (strongly recommended)

Backups live on the same disk as the system — **if the VPS is gone, so are they.** The installer creates a hook directory; drop an executable script in it and every verified backup calls it with the archive path:

```bash
sudo cp /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh.example \
        /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh
sudo nano /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh   # fill in rclone / scp
sudo chmod +x /etc/anyreality-resi-stack/backup-hooks.d/10-offsite.sh

# Verify now rather than tomorrow
sudo systemctl start anyreality-resi-stack-backup.service
sudo journalctl -u anyreality-resi-stack-backup.service -n 30 --no-pager
```

A failing hook fails the whole backup run, which the health check reports as a FAIL. That is deliberate: **an off-box copy you believe exists but does not** is the dangerous case. The local archive is kept regardless.

The health check warns when no hook is configured. Archives carry secrets, so the destination must be private and encrypted at rest.

### Restore drill (do this once after going live)

```bash
# 1. What do we have?
ls -lh /var/backups/anyreality-resi-stack/

# 2. Verify readability and contents without touching the live system
ARCHIVE=/var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz
tar -tzf "$ARCHIVE" | head -20
tar -tzf "$ARCHIVE" | grep -c '^etc/anyreality-resi-stack/'

# 3. Extract to a scratch directory and eyeball it (safe)
mkdir -p /tmp/restore-drill && tar -xzf "$ARCHIVE" -C /tmp/restore-drill
cat /tmp/restore-drill/manifest.txt
rm -rf /tmp/restore-drill
```

### Real restore

```bash
systemctl stop sing-box subscription-leaf 2>/dev/null || true
tar -xzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz -C /
systemctl daemon-reload
sing-box check -C /etc/sing-box/conf      # validate before starting
systemctl start sing-box
systemctl start subscription-leaf 2>/dev/null || true
anyreality-resi-stack-healthcheck
```

The traffic counter restarts from the moment of the restore (runtime state is not archived). To realign with the provider dashboard, apply a `USAGE_OFFSET_BYTES` — see [Troubleshooting → counter drift](TROUBLESHOOTING.md).

---

## 5. Rollback

| Situation | Action |
|---|---|
| Broke the config | Restore `/etc/sing-box` from a backup (section 4) |
| Bad sing-box release | `apt-get install sing-box=<older-version>` then `systemctl restart sing-box`; list versions with `apt-cache madison sing-box` |
| Clients broke after a protocol switch | Re-run the installer with the original `--protocol`; `secrets.env` is reused, keys are not regenerated |
| Want a clean slate | `bash install/install.sh --uninstall` (keeps secrets and backups by default) |

Re-running the installer is safe: it is idempotent and reuses an existing `secrets.env` rather than regenerating it — which matters, because regenerating keys invalidates every already-imported client.

---

## 6. Rotating the subscription token

The subscription URL is a credential. A screenshot, a client that syncs profiles to a third party, or a lost laptop all count as a leak.

```bash
sudo anyreality-resi-stack-rotate-sub-token --dry-run   # show what would change
sudo anyreality-resi-stack-rotate-sub-token
```

The script rewrites `SUB_TOKEN` in `secrets.env` and `TOKEN` in the service's EnvironmentFile, restarts the unit, and verifies that both `/healthz` and the new token path serve correctly. If the service does not come back healthy it rolls back to the previous token automatically.

After rotating:

1. **Every client must re-import the new URL** — the old one 404s.
2. If another host runs the aggregator against this node, update its `REMOTE_STATUS_URL` too, or its usage card freezes on the cached value.
3. If what leaked is the node password (`ANYTLS_PASSWORD`) rather than just the URL, rotating the token is not enough — delete `secrets.env` and re-run the installer, at the cost of re-importing on every client.

---

## 7. Enabling HTTPS for the subscription (do this if you own a domain)

By default the subscription is plain HTTP on :80, so anyone on the path sees the token and the node password inside the profile. **If you own a domain, turn TLS on** — the subscription servers support it natively via the Python standard library, with no extra dependency:

```bash
# 1. Point the domain at this host and issue a certificate
#    (stop the subscription service first; certbot --standalone needs :80)
sudo systemctl stop subscription-leaf
sudo certbot certonly --standalone -d sub.example.com

# 2. Re-run the installer with the certificate paths. secrets.env is reused,
#    so keys are not regenerated and existing clients keep working.
sudo bash install/install.sh --node-name "US-Resi-01" --with-subscription \
  --sub-tls-cert /etc/letsencrypt/live/sub.example.com/fullchain.pem \
  --sub-tls-key  /etc/letsencrypt/live/sub.example.com/privkey.pem
```

The installer grants the unprivileged `anyreality-sub` user group-read access to the certificate and key, and writes `TLS_CERT_FILE` / `TLS_KEY_FILE` into the EnvironmentFile. Once enabled:

- The subscription URL becomes `https://sub.example.com/<TOKEN>/` — **use the hostname the certificate was issued for, not the IP.**
- The health check switches to HTTPS automatically and additionally fails if the certificate expires within 7 days. Certificate expiry is a classic silent outage: every client refuses the subscription while a naive liveness probe still reports green.
- After a certbot renewal the service must restart to pick up the new certificate. Add a deploy hook:

```bash
echo 'systemctl restart subscription-leaf' | \
  sudo tee /etc/letsencrypt/renewal-hooks/deploy/restart-subscription.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-subscription.sh
```

Without a domain you are stuck on HTTP: treat the subscription URL as a password and rotate it (section 6) at any suspicion of a leak.

---

## 8. Known boundaries

Design trade-offs, not open bugs — but know them before going live:

- **Without a domain the subscription can only be plain HTTP.** With one, see section 7.
- **Traffic accounting is NIC-level**: it sums whole-host `rx+tx`, including OS updates and other non-proxy traffic, so it only approximates the provider dashboard.
- **Single host, no HA.** systemd restarts sing-box indefinitely (`StartLimitIntervalSec=0`, so repeated failures never park the unit permanently), but if the machine dies, the node dies.
- **Single user.** No multi-user support, no billing, no panel.

The subscription service runs as the unprivileged `anyreality-sub` user with only `CAP_NET_BIND_SERVICE` for binding :80. systemd reads the EnvironmentFile as root *before* dropping privileges, so `secrets.env` stays 0600 root-only and is unreadable from the HTTP server itself.

---

## Related docs

- [Deployment](DEPLOYMENT.md): blank VPS to running node.
- [Troubleshooting](TROUBLESHOOTING.md): connection failures, Reality handshakes, counter drift.
- [Subscription server design](SUBSCRIPTION.md): leaf/aggregator endpoints and cache behaviour.
