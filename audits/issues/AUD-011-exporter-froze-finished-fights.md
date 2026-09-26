# AUD-011 — The exporter froze finished fights mid-round

- **Status:** Fixed in `d688257` (deployed and arena restarted 2026-09-25)
- **Priority:** P0 — public correctness
- **Type:** Export / data integrity
- **Evidence:** 162 of 200 published fight files frozen at a live snapshot; #3900 ended by KO at tick 79,350 but was published in R3 REVEAL
- **Scope:** `packages/qdojo/src/qdojo/combat/export.py` (`export_all`)

## Finding

`export_all` wrote a fight's files while the fight was live and later skipped any finished fight whose file already existed. The site therefore showed about 160 fights as "deadline passed, awaiting advance", replays stopped before their ending, and fighter scouting saw only a handful of fights ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.1).

## Acceptance criteria

- [x] Fight files carry `final: true` and only files written final are skipped.
- [x] Regression test: a fight exported while live is rewritten when it ends (`test_live.py`, done).
- [x] After the restart, 194 of 200 published files were final; the rest were genuinely live.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
