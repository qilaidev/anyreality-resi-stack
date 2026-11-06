# Contributing

Thanks for considering a contribution. The hard rules first.

## Hard rules | 硬性规则

1. **Never commit secrets.** UUIDs, Reality keys, server IPs, subscription tokens, `*.env`, `*.key`, `*.pem`, `*.tar.gz`. The CI `redact` workflow will fail your PR if any leak; the local `make redact` command catches them before you push.
2. **`zh-CN` is the source of truth.** If you change a doc, update `docs/zh-CN/` first; the English mirror in `docs/en/` follows. PRs that only touch one of the two will be asked to mirror to the other.
3. **Lint must be green.** `make lint` runs shellcheck + shfmt + ruff + yamllint + jsonlint. CI is strict; warnings count as failures.
4. **Installer must be idempotent.** Every `install/lib/*.sh` phase function must be safely re-runnable. Use `ensure_line`, check for existing state, prefer `cp -a` over destructive mv.
5. **Templates use `@@VAR@@` placeholders, never real values.** Examples in `examples/` are *generated* by `scripts/make-example.sh` from RFC 5737 doc IPs and sentinel UUIDs; do not edit them by hand — regenerate.

## Workflow

```bash
git clone https://github.com/qilaidev/anyreality-resi-stack.git
cd anyreality-resi-stack

# Install tooling once
brew install shellcheck shfmt
pip install ruff yamllint
npm i -g markdown-link-check

# Make changes, then before pushing:
make test
make lint
make redact
make mdcheck
make examples       # regenerates examples/ from templates/; if diff, commit
```

## PR checklist

- [ ] `make test` and `make lint` pass locally
- [ ] `make redact` passes (no leaked secrets, no new unrecognized UUID-shape strings)
- [ ] `make mdcheck` passes (Markdown links still resolve)
- [ ] If you changed templates: `make examples` re-run, diff committed
- [ ] If you changed `docs/zh-CN/`: mirrored to `docs/en/`
- [ ] If you changed an `install/lib/*.sh` phase: confirmed idempotent (re-ran twice, second run = no-op)
- [ ] If you changed protocol-touching code: tested end-to-end on at least one real VPS
- [ ] PR description explains *why*, not just *what*

## Local testing of the installer

Always use `--dry-run` first:

```bash
sudo bash install/install.sh --node-name test --dry-run
```

Real install: spin up a throwaway Ubuntu 22.04 VPS, snapshot it, run the installer, exercise the flow, then destroy. Do **not** test on a server holding live credentials.

## Adding a new translation

Open an issue titled `translation: <language>` and we'll create a `docs/<lang>/` skeleton with file stubs pointing to the EN version as a fallback. Start with `README.md` and `DEPLOYMENT.md` — they cover 80% of new-user landing traffic.

## Code style

- Bash: `set -Eeuo pipefail`, 2-space indent (`.editorconfig`), shellcheck-clean. Disable rules only inline with a justification comment.
- Python: ruff strict mode, type hints encouraged, standard library only (zero third-party deps is a project invariant for the subscription servers).
- Markdown: keep lines reasonable but don't auto-wrap; tables OK; mermaid OK.

## Out of scope (please don't PR these)

- Web admin panel / GUI installer
- Docker / Kubernetes / Helm chart
- Multi-user / billing system
- Automatic SSL cert provisioning (Reality doesn't need certs)
- Anything that turns this into "yet another machine-pool selling business"

The project is a *toolkit for individuals running their own VPS*. Keep it small.
