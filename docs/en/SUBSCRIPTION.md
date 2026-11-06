# Subscription server design

## Why ship our own subscription server

The protocol alone only needs sing-box running on the server. The **subscription service** is an extra layer: it publishes client config files (sing-box JSON, Clash YAML) over HTTP. It is worth writing rather than adopting an existing one because:

1. **Clients get "sync subscription" / "update subscription"**: when you later change the node (new IP, new SNI, add a node), clients pick it up on the next refresh — no manual edits on each device.
2. **Usage cards**: via the `Subscription-Userinfo` response header (v2rayN-community convention), clients render "X used / Y total / expires Z". That requires the server to actually know how much has been used.
3. **Health checks**: `/healthz` lets uptime monitoring probe directly.
4. **Aggregation / HA**: in dual-node setups, the aggregator polls the leaf's `/status` and serves a unified subscription YAML — clients subscribe to a single URL.

Existing tools (3x-ui, Sub-Hub, Sub-Store) either pull in a full admin panel or rely on external workers / Redis. The implementation here is **standard-library-only Python** — auditable and dependency-free.

Three files: `_common.py` holds everything shared (routing, environment parsing, path safety, the HTTP server, optional TLS), while `leaf_server.py` and `aggregator_server.py` keep only the two things that genuinely differ — where the usage number comes from and what `/status` reports. All three are installed into the same directory, and each server anchors `sys.path` on its own location, so `import _common` needs no packaging and no `PYTHONPATH`.

**Runs unprivileged**: the subscription service runs as the system user `anyreality-sub` with only `CAP_NET_BIND_SERVICE` for binding :80. systemd reads the EnvironmentFile as root *before* dropping privileges, so `secrets.env` stays 0600 root-only — the HTTP server itself cannot read the node keys.

**Optional TLS**: set `TLS_CERT_FILE` + `TLS_KEY_FILE` (or pass `--sub-tls-cert` / `--sub-tls-key` at install time) to serve the subscription over HTTPS with a TLS 1.2 floor. It needs a certificate for a real hostname — see the [operations runbook](OPERATIONS.md).

> **One URL, two formats**: the server picks sing-box `profile.json` or Clash `profile.yaml` for `/<TOKEN>/` based on the client's User-Agent (an explicit filename always wins), so a household mixing sing-box phones and Clash desktops needs only one address. Both files come from the same `scripts/build_profile.py` and the same params, so they cannot drift apart; under `--protocol anytls-reality` only `profile.json` exists (mihomo cannot express that node). The server's own logic is unchanged: serve files by token, read NIC counters, usage cards, `/healthz`, `/<token>/status`.

---

## Two servers, two roles

| Server | File | Where it runs |
|---|---|---|
| **Leaf** | `subscription/leaf_server.py` | On every host running sing-box. Reads `/sys/class/net/<iface>/statistics/*_bytes`, accumulates billing-period traffic, and emits `Subscription-Userinfo`. |
| **Aggregator** | `subscription/aggregator_server.py` | On the data-center backup node in a dual-node setup. **Polls** the leaf's `/<TOKEN>/status` JSON, **caches** the result, and serves a unified Clash YAML listing both nodes. Falls back to the cache when the leaf is briefly unreachable. |

Single-node deployments run only the leaf. Dual-node deployments run both.

---

## Endpoint contract

Whether leaf or aggregator, the external contract is the same:

| Method | Path | Response |
|---|---|---|
| `GET`/`HEAD` | `/healthz` | `200 {"ok": true, "service": "<PROFILE_TITLE>"}` |
| `GET`/`HEAD` | `/<TOKEN>/` | Default subscription file, chosen between `profile.json` and `profile.yaml` by User-Agent, falling back to `DEFAULT_TARGET`; includes the usage-card headers |
| `GET`/`HEAD` | `/<TOKEN>/<filename>` | Named subscription file (leaf only; aggregator serves only the default). `FILE_DIR` may hold several profiles served by filename |
| `GET`/`HEAD` | `/<TOKEN>/status` | Machine-readable JSON usage summary |
| anything else | * | `404` |

**Key response headers:**

```http
Profile-Title: US-Resi-01
Profile-Update-Interval: 24
Content-Disposition: attachment; filename*=UTF-8''profile.json
Subscription-Userinfo: upload=0; download=10485760; total=1063004405760; expire=0
```

`Subscription-Userinfo` is a de-facto v2rayN-community standard; v2rayN, Clash Verge, Stash, Shadowrocket, and most maintained clients parse it.

---

## Configuration (environment)

Full reference in `templates/env/subscription-leaf.env.example` and `subscription-aggregator.env.example`. Highlights:

**Leaf:**

| Variable | Required | Purpose |
|---|---|---|
| `TOKEN` | ✓ | URL path prefix; the server only answers requests under `/<TOKEN>/` |
| `INTERFACE` | ✓ | NIC name, used to read `rx_bytes` / `tx_bytes` |
| `FILE_DIR` | | Directory of profile files (default `/etc/anyreality-resi-stack/files`); may hold several profiles |
| `DEFAULT_TARGET` | | Filename returned by `/<TOKEN>/` when the User-Agent is unrecognised; default `profile.json` |
| `STATE_FILE` | | Persistent billing-period counter |
| `USAGE_OFFSET_BYTES` | | Calibration baseline (use this when the counter starts mid-month) |
| `BILLING_CYCLE_DAY` | | Provider reset day, default `1` for calendar months |
| `USAGE_POLL_INTERVAL_SECONDS` | | Background sampling interval, default `60` |
| `COUNT_CURRENT_BOOT_ON_INIT` | | Count bytes already present in this boot on first state creation, default `true` |
| `TOTAL_BYTES` | | Plan quota (display only) |
| `EXPIRE_TS` | | Plan expiry Unix timestamp; `0` hides it |
| `REQUEST_TIMEOUT_SECONDS` | | Per-client socket timeout, default `10` |

**Aggregator:**

| Variable | Required | Purpose |
|---|---|---|
| `TOKEN` | ✓ | Independent of the leaf's token |
| `REMOTE_STATUS_URL` | ✓ | The leaf's `/status` URL, fetched on every poll |
| `REMOTE_TIMEOUT_SECONDS` | | Timeout for each leaf status poll, default `3` |
| `MAX_REMOTE_STATUS_BYTES` | | Maximum bytes read from one leaf status response, default `65536` |
| `CACHE_FILE` | | Last-known-good remote status |
| `CACHE_TTL_SECONDS` | | Cache freshness window (default 60) |
| `REMOTE_POLL_INTERVAL_SECONDS` | | Background leaf polling interval (default follows `CACHE_TTL_SECONDS`) |
| `FALLBACK_USED_BYTES` | | Fallback when neither cache nor leaf is available |
| `REQUEST_TIMEOUT_SECONDS` | | Per-client socket timeout, default `10` |

---

## Semantics of the traffic counter

**The leaf counts the host's billing-period NIC RX+TX:**

```
read /sys/class/net/<INTERFACE>/statistics/rx_bytes
read /sys/class/net/<INTERFACE>/statistics/tx_bytes
sample in the background every USAGE_POLL_INTERVAL_SECONDS
accumulate by provider billing period, reset on BILLING_CYCLE_DAY
first sample counts current-boot bytes by default, or set COUNT_CURRENT_BOOT_ON_INIT=false for baseline-only mode
detect reboots via boot_id — add the new boot's current counter into period usage
add USAGE_OFFSET_BYTES before returning to clients (manual calibration)
```

The honest bounds of this:

✅ Accurate enough for client-side "how much do I have left this month" reminders.
✅ Within an order of magnitude of "how much did I burn this month."
❌ **Not the same as your VPS provider's billing**. Providers may bill on 95th-percentile, on outbound only, on 5-minute peaks — entirely different units.
❌ If the host runs other workloads (a personal web server, backups), that non-proxy traffic is included too.

When the provider dashboard is much higher than the subscription card, the usual cause is "the subscription server started later than the billing period did" or the provider's reset day is not the first day of the month. Set `BILLING_CYCLE_DAY` to the provider reset day, then apply a `USAGE_OFFSET_BYTES` to catch up if needed (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md), "Traffic counter drifts" section).

---

## Aggregator's cache-fallback logic

`current_usage()` resolution order:

1. **Cache fresh (< `CACHE_TTL_SECONDS`)** → use cache, do not bother the leaf
2. **Cache stale or missing** → pull from leaf, refresh cache
3. **Leaf unreachable** → use the last cached value (even if stale)
4. **No cache either** → fall back to `FALLBACK_USED_BYTES`

The aggregator also refreshes the leaf cache in the background every
`REMOTE_POLL_INTERVAL_SECONDS` seconds, so the card remains warm even when no
client is pulling the subscription URL.

Why: clients refresh on `Profile-Update-Interval` (default 24 h). If the leaf is mid-restart at that moment, **returning 0 would yank the client's usage card back to zero** until the next refresh — a jarring visual jump that confuses users far more than "the number is slightly stale."

The fallback exists so the client card is **monotonic and never regresses**; admitting "slightly old data" is friendlier than admitting "data is missing."

---

## Running locally / debugging

The services are systemd-managed:

```bash
systemctl status subscription-leaf            # single-node
systemctl status subscription-aggregator      # the aggregator on the DC node
journalctl -u subscription-leaf -n 50 --no-pager
journalctl -u subscription-aggregator -n 50 --no-pager
```

Both HTTP servers set a per-client socket timeout and use daemon worker threads.
This keeps abandoned or very slow subscription clients from holding the public
`:80` service indefinitely. If you are behind a very slow reverse proxy, raise
`REQUEST_TIMEOUT_SECONDS` in the service env file and restart the service.

Run locally without systemd (for development):

```bash
cd /opt/anyreality-resi-stack/subscription
export TOKEN=test FILE_DIR=$(mktemp -d) INTERFACE=lo
echo '{"foo": "bar"}' > "$FILE_DIR/profile.json"
python3 leaf_server.py
# another terminal:
curl -i http://127.0.0.1:80/healthz
curl -I http://127.0.0.1:80/test/
```

---

## Next

- First deployment → [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)
- Deploy aggregator → [DUAL-NODE.md](DUAL-NODE.md)
- Usage card missing / counter wrong → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
