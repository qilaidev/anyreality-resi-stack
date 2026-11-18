<!-- Read CONTRIBUTING.md first. -->

## What & why

<!-- One paragraph on what changes and why. The "why" matters more than the "what" — the diff already tells us the what. -->

## Checklist

- [ ] `make lint` passes locally
- [ ] `make redact` passes (no leaked secrets, no new unrecognized UUID-shape strings)
- [ ] `make mdcheck` passes (Markdown links still resolve)
- [ ] If templates changed: `make examples` re-run, diff committed
- [ ] If `docs/zh-CN/` changed: mirrored to `docs/en/`
- [ ] If an `install/lib/*.sh` phase changed: confirmed idempotent (ran twice, second run = no-op)
- [ ] If protocol-touching: tested end-to-end on at least one real VPS

## Out of scope confirmation

- [ ] This PR does **not** add a web admin panel, Docker setup, multi-user billing, or automatic SSL — those are intentionally out of scope per `CONTRIBUTING.md`.
