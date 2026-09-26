# AUD-016 — `qdojo combat bot run --planner` forfeited its first local fight

- **Status:** Fixed in `66c0951` (deployed 2026-09-25)
- **Priority:** P1 — builder onboarding
- **Type:** CLI
- **Evidence:** Reproduced on a fresh devnet by the docs review; the advertised command failed for every new builder
- **Scope:** `combat/cli.py`, `combat/chain_cli.py`

## Finding

The local loop kept advancing ticks while the planner decided in the background, so the commit window closed before the plan arrived.

## Acceptance criteria

- [x] The loop holds the tick while a planner decides, up to `--budget-ms`.
- [x] Regression test that fails on the old code.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
