# Security policy

> [!IMPORTANT]
> **Compliance & Acceptable Use Notice / 合规与授权使用声明**  
> This repository provides Infrastructure-as-Code (IaC) configuration templates and local diagnostics strictly for **authorized cross-region edge gateway administration, localization QA, and WAN transport resilience research**. It does not host or distribute any servers, IPs, bandwidth, or commercial proxy services, and must not be used for unauthorized cross-border networking or commercial resale in regulated jurisdictions (including Mainland China without statutory authorization). See [DISCLAIMER.md](DISCLAIMER.md).

## Threat model | 威胁模型

`anyreality-resi-stack` is a personal / small-team self-hosted edge gateway and transport deployment toolkit. Its threat model is:

| In scope | Out of scope |
|---|---|
| Server-side bash and Python correctness | Multi-tenant isolation |
| Supply-chain integrity (pinned sing-box GPG fingerprint, secret hygiene gates) | Defense against active network-wide traffic analysis or non-standard protocol bans |
| Secret hygiene (CI redact gate, mode-600 `secrets.env`, no plaintext credentials in repo) | Hardening of arbitrary upstream packages |
| Reasonable default firewall, fail2ban, SSH hardening behind explicit `--harden-ssh` flag | TPM / hardware-attested boot |

This is a tool for individuals and engineering teams running their own authorized servers, not a hardened enterprise multi-tenant product.

中文：本项目的威胁模型是"个人/小团队自托管边缘网关与传输部署栈"。安全努力集中在服务端脚本与 Python 实现的正确性、供应链完整性（sing-box apt 源 GPG 指纹锁定）、凭证卫生（CI 脱敏门禁、`secrets.env` 600 权限）、合理的防火墙与 fail2ban 缺省值。**不在范围**：多租户隔离、应对全域深度流量分析、硬件可信启动等。

## Secret handling | 凭证处理规范

**Never commit:** UUIDs, Reality private/public keys, subscription tokens, server IPs, `secrets.env`, `usage-state.json`, `usage-cache.json`, `*.tar.gz` config backups, SSH keys, or anything resembling a real credential.

**The CI gate (`scripts/redact.sh` + `.github/workflows/redact.yml`) enforces this** by:

- **Forbidden filename & glob blocking**: Rejecting sensitive filenames and archive patterns (`secrets.env`, `usage-state.json`, `usage-cache.json`, `*.key`, `*.pem`, `*.tar.gz`, `*.tar`, `*.zip`, `*.7z`) at PR time.
- **Shape-based secret detection**: Detecting unknown UUID-shape strings and 43-character base64url strings (the shape of Curve25519 Reality keys) that are not in the explicit placeholder allowlist or source-identifier exemptions.
- **Optional high-entropy credential hash gate (`scripts/.redact-denylist.sha256`)**: Supporting one-way SHA-256 hashes strictly for high-entropy credentials (such as revoked test/CI tokens or keys). **Never** store unsalted SHA-256 hashes of 32-bit IPv4 addresses in a public repository, as the 2³² IPv4 space is trivially reversible.

中文：`scripts/redact.sh` 与 CI 脱敏门禁执行三层拦截：① 敏感文件名与后缀黑名单（禁止提交 `secrets.env`、私钥、证书与配置归档）；② UUID 与 43 位 base64url（Curve25519 Reality 密钥形态）正则检测（仅放行显式占位符白名单与源码标识符）；③ 可选的高熵凭据 SHA-256 哈希门禁（`scripts/.redact-denylist.sha256` 仅用于高熵密钥/令牌校验，**严禁**将 32 位 IPv4 地址的无盐哈希存入公开仓库，防止被彩虹表逆向枚举）。

If you discover a security vulnerability or accidental credential exposure, **do not** open a public issue. Instead, [open a draft security advisory](https://github.com/qilaidev/anyreality-resi-stack/security/advisories/new).

## Subscription URL exposure | 订阅地址的暴露面

Read this before enabling `--with-subscription` or `--with-aggregator`.

The subscription server listens on **plain HTTP :80** and serves the client profile at `http://<server-ip>/<SUB_TOKEN>/`. That profile contains everything needed to use your node — the VLESS UUID (or AnyTLS password), the Reality public key, and the short id. Consequences you are accepting:

| Risk | Detail | Mitigation |
|---|---|---|
| **Cleartext in transit** | Anyone on the path (ISP, transit, Wi-Fi operator) can read the profile and the token when a client refreshes | Put a TLS reverse proxy in front of :80 (or pass `--sub-tls-cert` / `--sub-tls-key`), or fetch the profile once over `scp` and disable the subscription server |
| **Token is the only secret** | The token is a UUID generated per host; there is no password, rate limit, or IP allowlist. Anyone who learns the URL has your node | Never paste the full URL into issues, screenshots, pastebins, or chat groups. Treat it exactly like a password |
| **Guessable sibling paths** | Do not place backups, `*.bak`, or extra profile copies inside `FILE_DIR` — they are served under the same token path | Keep backups in `/var/backups/anyreality-resi-stack/`, which is never web-served |
| **Rotation is disruptive** | Rotating `SUB_TOKEN` or the node password invalidates every already-imported client | Rotate on real evidence of exposure, not on a schedule |

中文：订阅服务默认是 **HTTP 明文的 :80**，`http://<IP>/<SUB_TOKEN>/` 返回的配置里含节点凭据。这意味着：链路上任何人都能读到；token 是唯一凭证，泄露即等于送出节点；`FILE_DIR` 里的任何文件都会被同一 token 路径下发，**备份文件绝不要放进去**（放 `/var/backups/anyreality-resi-stack/`）。需要更强保护就在前面加一层 TLS 反代（或使用 `--sub-tls-cert` / `--sub-tls-key`），或者用 `scp` 取一次配置后直接关掉订阅服务。轮换 token / 密码会让所有已导入的客户端断连，**有实际泄露证据再轮换，不要定期轮换**。

## Reporting vulnerabilities | 漏洞上报

Open a draft security advisory (preferred), or email the maintainer privately. **Do not** file public GitHub issues for unpatched vulnerabilities.

We acknowledge reports within 7 days. No bug bounty — this is a volunteer project.

## What we do NOT support | 我们不支持的场景

- Running with cleartext `secrets.env` in any repo or in dotfiles
- Disabling the `--harden-ssh` warnings without keeping a parallel SSH session
- Sharing one UUID across multiple servers (regenerate per host)
- Restoring `usage-state.json` from one machine onto another (each leaf must maintain its own)
- Using `latest` sing-box tag in production (CI bumps the pinned version after testing)
- Storing unsalted IPv4 SHA-256 hashes inside `scripts/.redact-denylist.sha256`
- Any deployment violating applicable telecommunications laws or [DISCLAIMER.md](DISCLAIMER.md)
