# AUD-027 — Outside builders cannot enter the arena

- **Status:** Mitigated in 7557e2a and cb5a22d: built and tested on a local arena, disabled by default until the operator opens it (docs/operations.md §8)
- **Priority:** P1 — product
- **Type:** Product
- **Evidence:** Only operator-run bots fight in the arena; builders can practise only locally
- **Scope:** Arena lineup, registration, bot hosting policy

## Finding

The core loop (build, enter, climb, study) stops after local practice ([product review](../reports/2026-09-25-product-review.md)).

## Acceptance criteria

- [x] A registration path for outside fighters on the simulated chain first.
  A SchnorrQ-signed registration; the arena issues a simulated NFT, grants fake QU and registers the asset; the
  builder signs `REGISTER_FIGHTER` and every later action as Qubic-format transactions (`combat/join.py`,
  `qdojo combat join`, [build-a-bot.md](../../docs/build-a-bot.md) §8). Evidence: `tests/combat/test_join.py`
  (register, sign, fight a combat result to the end; refusals for bad signatures, unregistered keys, admin
  opcodes, oversized attachments, stale ticks, wrong contract, name reuse, caps and rate limits).
- [x] Decide who runs the bot (the builder, or a hosted runner with limits).
  The builder runs it. A hosted runner would execute untrusted code on a two-CPU host; the builder-run path
  needs no code execution on the server, only signature checks, quotas and a bounded inbox.
- [x] Disclosure rules for house and outside fighters (see AUD-006).
  `origin` = `house` / `outside` on every fighter in the export and the API, HOUSE/OUTSIDE badges on the
  fighter page and leaderboard. The wider AUD-006 policy questions stay open there.

**Open for the operator:** enable it (three switches in operations.md §8), choose the limits, and decide
whether outside fighters may win cup purses against house bots before any real QU exists.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
