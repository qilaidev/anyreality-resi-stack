# subscription/ — Python subscription servers for anyreality-resi-stack

`subscription/` 是 `anyreality-resi-stack` 的零依赖 Python 订阅服务子模块。它把 sing-box 节点（默认 AnyReality = AnyTLS + Reality，遗留可选 VLESS + Reality + Vision）转换成客户端可订阅的 HTTP 入口，并通过 `Subscription-Userinfo` 响应头显示流量卡片。

Two zero-dependency Python HTTP servers that turn the sing-box install into a
proper subscription endpoint with usage cards. They are part of the main
residential-IP AnyReality / VLESS Reality deployment stack — not a standalone
commercial subscription panel.

> 主项目文档 / Main project docs: [README.md](../README.md) ·
> [订阅服务设计](../docs/zh-CN/SUBSCRIPTION.md) ·
> [Subscription server design](../docs/en/SUBSCRIPTION.md)

## 适用场景 | When to use it

| 场景 | 使用方式 |
|---|---|
| 单节点 AnyReality / VLESS Reality 自用部署 | 在节点上运行 `leaf_server.py`，客户端订阅 `http://<server>/<TOKEN>/` |
| 住宅节点 + 数据中心备用节点 | 在住宅节点运行 leaf，在数据中心节点运行 `aggregator_server.py`，客户端只订阅 aggregator URL |
| 需要客户端显示用量 | 配置 `TOTAL_BYTES`、`BILLING_CYCLE_DAY`、`INTERFACE`，服务会采样网卡 RX+TX 并返回 `Subscription-Userinfo` |
| 不适合 | 多用户计费、账号到期管理、商业面板、跨租户隔离 |

## Why two servers

| Server | Role | Where it runs |
|---|---|---|
| `leaf_server.py` | Reads `/sys/class/net/<iface>/statistics/*_bytes` on the host where sing-box lives, samples usage in the background, serves the rendered sing-box / Clash profile, and emits `Subscription-Userinfo` headers. | On every node — at minimum, the residential node. |
| `aggregator_server.py` | Polls the leaf's `/<TOKEN>/status` JSON in the background, caches it, and serves a *unified* dual-node profile. Falls back to the cache if the leaf is unreachable. | On the data-center backup node when you run a dual-node deployment. |

`_common.py` holds everything the two share: routing, environment parsing,
path safety, the `Content-Disposition` shape, the HTTP server, and optional
TLS. Each server keeps only what genuinely differs — where the usage number
comes from and what `/status` reports. All three files are installed into the
same directory and each server anchors `sys.path` on its own location, so
`import _common` needs no packaging and no `PYTHONPATH`.

Both have **no third-party Python dependencies** — standard library only,
Python 3.10+. They are designed to run as `systemd` services installed by
`install/lib/subscription.sh` (`subscription-leaf.service` /
`subscription-aggregator.service`), under the unprivileged `anyreality-sub`
system account with just `CAP_NET_BIND_SERVICE` for binding :80. systemd reads
the EnvironmentFile as root *before* dropping privileges, so `secrets.env`
stays 0600 root-only and is unreadable from the HTTP server itself.

Every environment variable is parsed with range checks at startup: a typo exits
2 naming the offending variable rather than crash-looping on a bare traceback.

### Optional TLS

Set `TLS_CERT_FILE` and `TLS_KEY_FILE` (or pass `--sub-tls-cert` /
`--sub-tls-key` to the installer) to serve the subscription over HTTPS with a
TLS 1.2 floor. It needs a certificate for a real hostname, so it is opt-in —
see the [operations runbook](../docs/en/OPERATIONS.md).

## Which profile file is served

`DEFAULT_TARGET` decides what `/<TOKEN>/` returns. The installer sets it per
protocol:

| Protocol | `DEFAULT_TARGET` | Rendered from |
|---|---|---|
| `anytls-reality` (default) | `profile.json` — a full sing-box client config | `templates/singbox-client/client-single.json.tmpl` / `client-dual.json.tmpl` |
| `vless-vision` (legacy) | `profile.yaml` — a Clash profile | `templates/clash/client-single.yaml.tmpl` / `client-dual.yaml.tmpl` |

Note that the servers' own built-in fallback is `DEFAULT_TARGET=profile.yaml`;
the installer always writes an explicit value into the env file, so the
protocol you installed with is the one clients get.

## Endpoint contract

| Method | Path | Response |
|---|---|---|
| `GET`/`HEAD` | `/healthz` | `200 {"ok": true, "service": "<PROFILE_TITLE>"}` |
| `GET`/`HEAD` | `/<TOKEN>/` | Default profile file, with `Subscription-Userinfo` etc. |
| `GET`/`HEAD` | `/<TOKEN>/<filename>` | Named profile file (leaf only — aggregator only serves the default). |
| `GET`/`HEAD` | `/<TOKEN>/status` | Machine-readable JSON usage summary. |
| `GET` any other path | `404 Not Found`. |

The `Subscription-Userinfo` header follows the original
[`v2rayN` convention](https://github.com/2dust/v2rayN/wiki/%E5%88%86%E7%89%87%E8%A7%84%E5%88%99):
`upload=0; download=<bytes>; total=<bytes>; expire=<unix-ts-or-0>`.

> ⚠️ 订阅服务默认监听**明文 HTTP :80**，`/<TOKEN>/` 返回的配置里含节点凭据（AnyReality 密码或 VLESS UUID）。**订阅 URL 等同于凭证**，不要公开分享，也不要把备份文件放进 `FILE_DIR`。见 [SECURITY.md](../SECURITY.md#subscription-url-exposure--订阅地址的暴露面)。
>
> The server is plain HTTP on `:80` and the profile contains your node
> credential. Treat the subscription URL as a secret.

## State files

| File | Owner | Purpose |
|---|---|---|
| `/var/lib/anyreality-resi-stack/usage-state.json` | leaf | Monotonically increasing billing-period counter; defaults to calendar months, or set `BILLING_CYCLE_DAY` to match the provider reset day. |
| `/var/lib/anyreality-resi-stack/usage-cache.json` | aggregator | Last-known-good remote status; refreshed in the background and used as fallback when the leaf is down. |

Both paths are overridable with `STATE_FILE` / `CACHE_FILE`. On hosts upgraded
from v1.x (`reality-resi-stack`), the installer migrates the old directories to
the `anyreality-resi-stack` prefix in place.

The leaf samples usage every `USAGE_POLL_INTERVAL_SECONDS` seconds, so the
counter stays current even when no client is refreshing the subscription URL.
On first state creation, `COUNT_CURRENT_BOOT_ON_INIT=true` counts bytes already
present in the current boot. That makes the card track provider dashboards more
closely when the subscription server is installed after the VPS has already
been running.

State files are excluded from backups intentionally — they are runtime data,
not configuration.

State/cache writes use atomic replace with per-thread temporary files, so
parallel HTTP requests and background polling do not corrupt the JSON files.
The aggregator also caps each remote `/status` response with
`MAX_REMOTE_STATUS_BYTES` (default 64 KiB) before parsing it.

Config backups do include `/etc/anyreality-resi-stack/`, which holds the
subscription token and generated node credentials. Treat backup archives as
sensitive.

## Running locally (test) | 本地测试

```bash
export TOKEN=test-token
export FILE_DIR=$(pwd)/test-files
export STATE_FILE=$(mktemp)
export INTERFACE=lo
export PORT=8080
mkdir -p "$FILE_DIR" && echo 'foo: bar' > "$FILE_DIR/profile.yaml"
python3 leaf_server.py
# then: curl -i http://127.0.0.1:8080/healthz
#       curl -i http://127.0.0.1:8080/test-token/
#       curl -s  http://127.0.0.1:8080/test-token/status
```

`PORT` defaults to `80`, which needs root or `CAP_NET_BIND_SERVICE`; override
it for local runs. Tests live in [`tests/`](../tests) and run with `make test`:
accounting, cache fallback, environment validation, path safety, the
`Content-Disposition` shape, and an end-to-end suite that boots the real leaf
server (plain and TLS) on an ephemeral port and drives it over HTTP.
