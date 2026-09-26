# AUD-017 — Fighter records showed ranked fights only

- **Status:** Fixed in `d688257` (deployed 2026-09-25)
- **Priority:** P1 — public correctness
- **Type:** Export / site
- **Evidence:** Duel and cup fighters (tengu, baku, EVO-DS2, EVO-GEM2) showed 0-0-0 and PROVISIONAL 1000 after hundreds of fights
- **Scope:** `combat/export.py` (`records_by_mode`), `apps/web/combat/app.js` (fighter page, leaderboard)

## Finding

The contract's `record` counts ranked fights only, and the site presented it as the whole career.

## Acceptance criteria

- [x] Fighter files carry `records_by_mode`.
- [x] Fighter page shows a CAREER table; leaderboard win rate counts every mode.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
