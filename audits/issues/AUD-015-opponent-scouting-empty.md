# AUD-015 — Planners could not scout their opponent

- **Status:** Fixed in `0918949` (deployed 2026-09-25)
- **Priority:** P1 — builder experience
- **Type:** Protocol / observation
- **Evidence:** `history_manifest` was always empty although the docs promised opponent history
- **Scope:** `combat/scouting.py` (new), observation builder, `docs/api.md`, `apps/web/llms.txt`

## Finding

The observation carried no opponent history, so studying an opponent's published fights, a core promise of the game, was impossible.

## Acceptance criteria

- [x] `opponent_history` lists up to 10 finished fights with revealed plans, deterministic and within 24 KiB; never the current fight or a sealed plan.
- [x] Documented in `docs/api.md`, `docs/build-a-bot.md` and `llms.txt`.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
