# Troubleshooting

Ordered by "symptom → most-common cause → fix." Always start with these baseline checks:

```bash
systemctl status sing-box --no-pager
journalctl -u sing-box -n 50 --no-pager
ss -tlnp | grep ':443'
ufw status verbose
sing-box check -C /etc/sing-box/conf
```

Issue templates will ask for the output of these first.

---

## Client cannot connect

**Check protocol match first.** The default `vless-reality` works with both client families, so a protocol mismatch is unusual. Only `--protocol anytls-reality` is sing-box-only — in that mode the server generates **no Clash profile at all**, so Clash users find no YAML to import.

| Likely cause | How to check |
|---|---|
| Installed `anytls-reality` but need Clash | Reinstall with `--protocol vless-reality` (the default) |
| Cloud provider security group not allowing `443/tcp` | Check the provider console |
| UFW not allowing `443/tcp` | `ufw status` |
| `anytls-reality`: client `password` ≠ server `ANYTLS_PASSWORD` | Compare client password vs `ANYTLS_PASSWORD` in `/etc/anyreality-resi-stack/secrets.env` |
| `vless-reality`: client UUID mismatch | Compare client `vless://` UUID vs server `secrets.env` |
| Client Reality `public-key` wrong | Compare client `pbk=` / `public_key` vs server `REALITY_PUBLIC_KEY` |
| Client Reality `short_id` mismatch | Compare client `short_id` vs server config |
| Client `servername` / SNI ≠ server `server_name` | Both must be the same SNI (e.g. `addons.mozilla.org`) |
| Client lacks Reality support (legacy also needs `xtls-rprx-vision`) | Update to latest sing-box / v2rayN / Clash Verge |
| nginx/caddy/apache already holds 443 | `ss -tlnp \| grep 443` to see |
| sing-box config has an error | `sing-box check -C /etc/sing-box/conf` |

> Only one REALITY inbound file should exist at a time: `vless-reality` is `/etc/sing-box/conf/11_xtls-reality_inbounds.json`, `anytls-reality` is `11_anytls-reality_inbounds.json`. Both present means they fight over `443` and `sing-box check` fails. (`12_hysteria2_inbounds.json` and `13_vless-ws_inbounds.json` are the other two paths and do not conflict.)

---

## The client quits instantly / will not start after boot (rebooting sometimes helps)

**Symptom:** the client exits immediately after launch, or restarts in a loop.
Rebooting the machine helps sometimes and not others.

**Cause:** sing-box downloads every `type: remote` rule-set **during startup**, and any failure is
`FATAL`. The download goes through the group named by `download_detour` — and **on a cold start
urltest has no measurements yet and simply uses the first member**. If that member is dead on your
line, the download times out, the kernel dies, the app restarts it, and it hits the same wall.

"Rebooting fixed it" only means the timing changed and that download happened to succeed. **It was
never actually fixed.**

```bash
# If this shows up in the client log, the loop is still there
grep -c "raw.githubusercontent" "<your client kernel.log>"
```

**Profiles from this project inline every rule-set, so startup makes no network request** and cannot
fail this way. If it still happens, check in order:

1. **Is an old subscription from a decommissioned server still in the client?** Its `type: remote` +
   `download_detour` reintroduce the deadlock — **even when it is not the selected profile.** Delete
   it properly.
2. Is the client missing a local `.srs`? Some clients ship only a few rule-sets and turn any unknown
   tag into a remote URL. Compile them locally instead — no download needed:
   ```bash
   sing-box rule-set compile --output geosite-private.srs geosite-private.json
   ```
3. Confirm the published profile really has no remote sets:
   ```bash
   python3 /usr/local/lib/anyreality-resi-stack/check_profile.py \
     /etc/anyreality-resi-stack/files/profile.json
   ```

Details: [Networks in China §3](CHINA-NETWORK.md).

---

## The CDN relay connects, then dies every ~2m05s

**Symptom:** connections over the CDN relay drop at **2m05s / 2m06s / 2m07s**, suspiciously exact.

**These three suspects are all wrong** (all checked):

| Suspect | Reality |
|---|---|
| nginx `proxy_read_timeout` | This project's template sets 3600s — it cannot produce 125s |
| Client TCP keepalive / `keep-alive-idle` | TCP keepalive is **hop-by-hop**; it terminates at the CDN edge, which never sees it |
| "The auto group picked a bad node" | Every node behaves identically |

**The cause is the CDN's idle timeout for a proxied WebSocket** (~100s on ordinary plans): with no
frames in either direction it closes. Keeping it alive needs an **application-level ping** — an
actual WebSocket frame — and sing-box's h2mux/smux/yamux emit none.

This project injects them at the origin. Confirm the injector is alive:

```bash
systemctl status ws-ping-inject
ss -tlnp | grep 18444                 # the injector is listening
nginx -T | grep -F "<your WS path>"   # -T (running config), not -t
```

A dead `ws-ping-inject` means every CDN tunnel drops at ~100s while sing-box and nginx both look
healthy. The health check reports it explicitly.

---

## Hysteria2 is installed, the server looks fine, and no client can connect

**Almost always a TCP-only firewall rule.** `ufw allow 443` opens **TCP only**; UDP is separate:

```bash
ss -ulnp | grep ':443'                    # the server really is listening on UDP
ufw status | grep -E '443/(tcp|udp)'      # both must be present
ufw allow 443/udp comment "hysteria2"     # add it if missing
```

What makes this one nasty: the inbound is valid, the process is listening, `sing-box check` passes
and the log is clean — **nothing on the server indicates a problem.** Only the clients time out.

---

## The alternate ports do not appear in `ss -tlnp`

**Expected, not a fault.** They are REDIRECTs in `nat/PREROUTING`, not listeners:

```bash
iptables -t nat -S ANYREALITY_ALTPORT        # the rules live here
iptables -t nat -L ANYREALITY_ALTPORT -v -n  # pkts/bytes is the real usage signal
```

And because the rewrite happens **before** filter/INPUT, UFW needs no rule for them — do not add
redundant ones.

---

## Telegram / Discord uploads stalling, voice choppy

This is the **canonical "residential-IP soft-throttle" symptom**, and **not** a protocol problem.

**Diagnose:**
- Speed tests pass
- Text messages fine
- Large files, voice, and video uploads visibly degraded
- The same account works fine on a non-proxied connection

**Root cause:** your residential /24 has bot history; Telegram/Discord anti-abuse downranks the whole subnet regardless of your specific account.

**Fix:** dual-node + smart routing (route Telegram/Discord through a data-center node). See [DUAL-NODE.md](DUAL-NODE.md).

**Quick mitigation** without touching the server: add a Clash routing rule that diverts TG/Discord through any non-residential proxy you have available:

```yaml
rules:
  - DOMAIN-SUFFIX,telegram.org,your-backup-proxy
  - DOMAIN-SUFFIX,t.me,your-backup-proxy
  - DOMAIN-SUFFIX,discord.com,your-backup-proxy
  - IP-CIDR,91.108.4.0/22,your-backup-proxy,no-resolve
  - IP-CIDR,91.108.16.0/22,your-backup-proxy,no-resolve
  - IP-CIDR,149.154.160.0/20,your-backup-proxy,no-resolve
  # everything else through your default
```

---

## Subscription URL works but no usage card in the client

```bash
curl -I http://your-server-ip/your-token
```

You should see:

- `Subscription-Userinfo`
- `Profile-Title`
- `Profile-Update-Interval`

If all are present but the client doesn't render → the **client doesn't support** the card (older v2rayN, some mobile Clash forks). Switch clients; this does not affect proxying.

If headers are missing → check the leaf logs:

```bash
journalctl -u subscription-leaf -n 50 --no-pager
```

---

## Counter doesn't match provider dashboard

**Short answer:** expected behavior, not a bug.

**Long answer:** the subscription server counts `/sys/class/net/<iface>/statistics/rx_bytes + tx_bytes` over the configured billing period. Providers may bill on:

- Outbound only (your `tx_bytes`, not `rx + tx`)
- 95th-percentile (not accumulation)
- 5-minute peaks
- Adding control-plane traffic (DHCP / ARP / your own SSH session bytes)
- A billing period starting on a provider-specific day such as the 11th

**Calibrate** (align the card to match the dashboard from this moment on):

```bash
CURRENT_TOTAL=$(( $(cat /sys/class/net/eth0/statistics/rx_bytes) + $(cat /sys/class/net/eth0/statistics/tx_bytes) ))
STATE_USED=$(python3 -c "import json; print(int(json.load(open('/var/lib/anyreality-resi-stack/usage-state.json'))['used_bytes']))")
BACKEND_USED=900000000000   # bytes used per your provider's dashboard

OFFSET=$((BACKEND_USED - STATE_USED))
sudo sed -i "s/^USAGE_OFFSET_BYTES=.*/USAGE_OFFSET_BYTES=${OFFSET}/" /etc/anyreality-resi-stack/subscription-leaf.env
sudo systemctl restart subscription-leaf
```

If your provider resets traffic on a non-first day of the month, also set `BILLING_CYCLE_DAY` before calibrating:

```bash
sudo sed -i "s/^BILLING_CYCLE_DAY=.*/BILLING_CYCLE_DAY=11/" /etc/anyreality-resi-stack/subscription-leaf.env
```

If `usage-state.json` does not exist yet or was cleared during restore, the leaf now creates state on the next background poll or status request. `USAGE_OFFSET_BYTES` may be negative; the server clamps the final reported value to zero or above.

---

## TLS self-handshake fails / Reality doesn't seem to work

```bash
echo | openssl s_client -connect 127.0.0.1:443 -servername addons.mozilla.org 2>/dev/null | grep subject=
```

Should return the certificate subject of `addons.mozilla.org`. If it returns something else (sing-box self-signed, `cannot connect`):

- **sing-box not installed / not running**: `systemctl status sing-box`
- **SNI misconfigured**: in the REALITY inbound file (`11_xtls-reality_inbounds.json` or `11_anytls-reality_inbounds.json`), `tls.server_name` and `tls.reality.handshake.server` must be **exactly equal**
- **Server can't reach the SNI host**: try `curl -v https://addons.mozilla.org/` directly from the VPS
- **Reality private/public keys mismatched**: regenerate with `sing-box generate reality-keypair`, update both server and client

---

## fail2ban locked me out

```bash
fail2ban-client status sshd                   # see banned IPs
fail2ban-client set sshd unbanip 1.2.3.4      # unban
```

Prevention: always keep a parallel SSH session before applying `--harden-ssh`. Default jail: 5 failures → 1 h ban.

---

## sing-box service fails after upgrade

```bash
journalctl -u sing-box -n 100 --no-pager
sing-box check -C /etc/sing-box/conf
```

Most often a schema change in the new sing-box version. Cross-reference the [sing-box release notes](https://github.com/SagerNet/sing-box/releases). Short-term:

```bash
apt-get install -y sing-box=<last-known-good-version>
apt-mark hold sing-box   # pin
```

Then open an issue on this repo so we can ship the schema fix.

---

## NTP time sync fails

```bash
timedatectl
chronyc sources -v
```

Multiple sources with `Reach=0` usually means the provider blocks outbound `123/UDP`. **Does not block proxying** (VLESS doesn't depend on tight clock sync), but skews log timestamps. Switch to NTS:

```bash
sudo sed -i 's|^pool .*|pool time.cloudflare.com iburst nts|' /etc/chrony/chrony.conf
sudo systemctl restart chrony
```

---

## Broken config / want to roll back

```bash
ls /var/backups/anyreality-resi-stack/
tar -tzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-2026-05-17-120000.tar.gz | head
```

Restore (stop services first):

```bash
systemctl stop sing-box
tar -xzf /var/backups/anyreality-resi-stack/anyreality-resi-stack-XXXX.tar.gz -C /
systemctl daemon-reload
systemctl start sing-box
sing-box check -C /etc/sing-box/conf
```

⚠️ Backups **do not** include `/var/lib/anyreality-resi-stack/usage-state.json` or `usage-cache.json` (runtime state), so after a restore the counter restarts. Archives include `/etc/anyreality-resi-stack/`, which contains secrets and tokens; do not share them publicly. Apply a `USAGE_OFFSET_BYTES` after restore (see "Counter doesn't match provider dashboard" above). sing-box logs are excluded too.

For the full backup verification, restore drill, and rollback procedure see the [operations runbook](OPERATIONS.md).

---

## Exit IP is not the expected residential IP

```bash
curl --proxy socks5h://127.0.0.1:7891 https://ipinfo.io
```

If the IP returned isn't your residential IP:

- Client rules may have routed the request elsewhere — check the rule match log in the client
- DNS contamination: client may have resolved direct without sniffing — check Clash's `mode: rule` and `dns:` section
- Your residential node may be down and the client fell back to a backup — `systemctl status sing-box` on the residential node

---

## Cloudflare CAPTCHA spins forever / never passes

**These are two independent problems with completely different causes:**

| Symptom | Cause | Section |
|---|---|---|
| CAPTCHA appears **often**, but one click gets you through | Poor ASN reputation of the exit IP | "Frequent CAPTCHAs" below |
| The page **spins forever**, keeps re-challenging, clicking does nothing | The challenge widget cannot load — almost always IPv6 | Right below |

### Spins forever → the node almost certainly has no IPv6

Cloudflare loads its challenge widget from `brunhild.challenges.cloudflare.com`,
and that host has had **AAAA records only, no A record**, for a long time
(cross-checked against 1.1.1.1 / 8.8.8.8 / 9.9.9.9). With no usable IPv6 egress
the widget's JS simply never downloads, so the challenge can never complete.

This one is **very hard to guess**: the only trace on the server is a single
error-log line:

```
lookup brunhild.challenges.cloudflare.com: empty result
```

**Diagnose first:**

```bash
# 1) Does the node have a global IPv6 address at all? (0 means no)
ip -6 addr show scope global | grep -c inet6

# 2) Can it actually egress over IPv6?
curl -6 -sS --max-time 8 -o /dev/null -w '%{http_code}\n' https://brunhild.challenges.cloudflare.com/

# 3) How often has this failed (helps pinpoint when it started)
journalctl -u sing-box --no-pager | grep -c "empty result"
```

`anyreality-resi-stack-healthcheck` now performs this check and warns when
IPv6 egress is missing.

**Fixes, in order of preference:**

1. **Enable IPv6 on the VPS** (the real fix). Nearly every provider hands out a
   free /64; enable it in the panel and configure the interface. Re-run step 2
   above to confirm.
2. This repo's templates already exempt the host from the IPv4-only strategy
   (`templates/singbox/05_dns.json` routes `challenges.cloudflare.com` with
   `prefer_ipv4` — use A when present, fall back to AAAA). Reinstall or port
   that block to existing nodes.
   ⚠️ In sing-box 1.12+, `strategy` belongs to the **DNS rule's `action: route`**,
   not to the server object; putting it on the server errors with
   `unknown field "strategy"`.
3. If IPv6 is truly unavailable: either accept that CAPTCHA-heavy sites are
   unusable, or attach an IPv6 tunnel (WARP, HE.net, …) and point this host at it.

> **On the client the fix has to live in the DNS section, not in routing.** In
> TUN mode — what this project recommends — the application resolves the name
> *before* opening a socket, so under `ipv4_only` the lookup has already come
> back empty and no route rule ever gets a say. The client templates therefore
> give the suffix its own `prefer_ipv4` entry in `dns.rules` (resolved over the
> node). The route rule pinning it to the node is kept as well — it costs
> nothing and states the intent. Don't drop either one.

### Frequent CAPTCHAs (that you can pass) → exit ASN reputation

This has **nothing** to do with protocol, SNI, camouflage or client — switching
to a different protocol or changing the SNI will not help at all. Identify the exit ASN:

```bash
curl -sS https://ipinfo.io/org      # run on the node
dig -x <your-node-ip> +short        # rDNS often names the upstream datacenter
```

If it lands in one of the ASNs dominated by cheap VPS resale, Cloudflare issues
challenges **probabilistically** — which is why it feels like "often" rather
than "always". This is precisely why this project favours **residential** exits:
residential ranges start with a much better reputation.

Mitigation: route the affected domains through a better-reputation exit — that
is exactly what this project's dual-node split is for, see [DUAL-NODE.md](DUAL-NODE.md).

> ⚠️ **Measurement trap**: plain `curl` against a Cloudflare site returns `403`
> no matter what, because curl has no browser TLS/HTTP2 fingerprint and runs no
> JS. **That does not mean your IP is flagged.** To tell whether the IP itself is
> being challenged, use a client with a real fingerprint (e.g. Python
> `curl_cffi` with `impersonate="chrome131"`) and look for the
> `cf-mitigated: challenge` response header.

---

## Still stuck?

When filing an issue, please include:

- `journalctl -u sing-box -n 100 --no-pager`
- `sing-box version`
- `cat /etc/os-release | head -3`
- expected vs actual behavior
- **Do NOT** paste UUIDs, Reality keys, or server IPs

The issue template reminds you again.

Related docs:

- First deployment: [Beginner guide](BEGINNER_GUIDE.md)
- Deciding whether dual-node routing is needed: [Dual-node smart routing](DUAL-NODE.md)
- Choosing between this stack, 3x-ui, x-ui, and manual config: [Comparison](COMPARISON.md)
