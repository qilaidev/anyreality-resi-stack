# Security policy

## Threat model | 威胁模型

`anyreality-resi-stack` is a personal / small-team self-hosted proxy toolkit. Its threat model is:

| In scope | Out of scope |
|---|---|
| Server-side bash and Python correctness | Multi-tenant isolation |
| Supply-chain integrity (pinned sing-box GPG fingerprint, hash-only secret denylist) | Defense against state-level adversaries with traffic analysis |
| Secret hygiene (CI redact gate, mode-600 secrets.env, no plaintext in repo) | Hardening of arbitrary upstream packages |
| Reasonable default firewall, fail2ban, SSH hardening behind explicit `--harden-ssh` flag | TPM / hardware-attested boot |

This is a tool for individuals running their own VPS, not a hardened enterprise product.

中文：本项目的威胁模型是"个人/小团队自托管代理"。安全努力集中在服务端脚本与 Python 实现的正确性、供应链完整性（sing-box apt 源 GPG 指纹锁定）、凭证卫生（CI 哈希脱敏门禁、`secrets.env` 600 权限）、合理的防火墙与 fail2ban 缺省值。**不在范围**：多租户隔离、对抗国家级流量分析、硬件可信启动等。

## Secret handling | 凭证处理规范

**Never commit:** UUIDs, Reality private/public keys, subscription tokens, server IPs, `secrets.env`, `usage-state.json`, `usage-cache.json`, `*.tar.gz` config backups, SSH keys, or anything resembling a real credential.

**The CI gate (`scripts/redact.sh` + `.github/workflows/redact.yml`) enforces this** by:

- Maintaining a SHA-256 hash list (`scripts/.redact-denylist.sha256`) of known-leaked credentials from prior incidents — the hashes are *not* leaks because they're cryptographic one-way.
- Detecting unknown UUID-shape strings and 43-character base64url strings (the shape of Curve25519 Reality keys) that aren't in the placeholder allowlist.
- Rejecting forbidden filename patterns at PR time.

If you discover a credential leak, **do not** open a public issue. Instead, [open a draft security advisory](https://github.com/qilaidev/anyreality-resi-stack/security/advisories/new).

## Subscription URL exposure | 订阅地址的暴露面

Read this before enabling `--with-subscription` or `--with-aggregator`.

The subscription server listens on **plain HTTP :80** and serves the client profile at `http://<server-ip>/<SUB_TOKEN>/`. That profile contains everything needed to use your node — the AnyTLS password (or the VLESS UUID), the Reality public key, and the short id. Consequences you are accepting:

| Risk | Detail | Mitigation |
|---|---|---|
| **Cleartext in transit** | Anyone on the path (ISP, transit, Wi-Fi operator) can read the profile and the token when a client refreshes | Put a TLS reverse proxy in front of :80, or fetch the profile once over `scp` and disable the subscription server |
| **Token is the only secret** | The token is a UUID generated per host; there is no password, rate limit, or IP allowlist. Anyone who learns the URL has your node | Never paste the full URL into issues, screenshots, pastebins, or chat groups. Treat it exactly like a password |
| **Guessable sibling paths** | Do not place backups, `*.bak`, or extra profile copies inside `FILE_DIR` — they are served under the same token path | Keep backups in `/var/backups/anyreality-resi-stack/`, which is never web-served |
| **Rotation is disruptive** | Rotating `SUB_TOKEN` or the node password invalidates every already-imported client | Rotate on real evidence of exposure, not on a schedule |

中文：订阅服务是 **HTTP 明文的 :80**，`http://<IP>/<SUB_TOKEN>/` 返回的配置里含节点密码。这意味着：链路上任何人都能读到；token 是唯一凭证，泄露即等于送出节点；`FILE_DIR` 里的任何文件都会被同一 token 路径下发，**备份文件绝不要放进去**（放 `/var/backups/anyreality-resi-stack/`）。需要更强保护就在前面加一层 TLS 反代，或者用 `scp` 取一次配置后直接关掉订阅服务。轮换 token / 密码会让所有已导入的客户端断连，**有实际泄露证据再轮换，不要定期轮换**。

## Reporting vulnerabilities | 漏洞上报

Open a draft security advisory (preferred), or email the maintainer privately. **Do not** file public GitHub issues for unpatched vulnerabilities.

We acknowledge reports within 7 days. No bug bounty — this is a volunteer project.

## What we do NOT support | 我们不支持的场景

- Running with cleartext `secrets.env` in any repo or in dotfiles
- Disabling the `--harden-ssh` warnings without keeping a parallel SSH session
- Sharing one UUID across multiple servers (regenerate per host)
- Restoring `usage-state.json` from one machine onto another (each leaf must maintain its own)
- Using `latest` sing-box tag in production (CI bumps the pinned version after testing)
