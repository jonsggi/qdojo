# AUD-026 — Full history needs a read model, not static files

- **Status:** Fixed in 7557e2a and cb5a22d (deployment pending: install `deploy/systemd/qdojo-combat-api.service`, redeploy the site)
- **Priority:** P1 — product foundation
- **Type:** Architecture
- **Evidence:** The site keeps the 200 most recent fights as static JSON; fighter pages, form and scouting are limited to what is still published
- **Scope:** Exporter, data server, site

## Finding

Static files with retention cannot serve full-history stats, pagination, seasons or search ([product review](../reports/2026-09-25-product-review.md)).

## Acceptance criteria

- [x] A SQLite or Postgres read model fed from the event journal, rebuildable at any time.
  `combat/readmodel.py` replays the devnet journal into its own contract and indexes every fight, fighter,
  per-mode record, rating change, season, cup, duel and ownership row. Evidence: `tests/combat/test_readmodel.py`
  (an incremental database with a mid-run restart from its snapshot equals a rebuild, table by table; torn lines;
  replaced journals). On a copy of the live journal (2026-09-26): 199,182 records, 5,223 fights, rebuild 4 min
  (161 s CPU), 27 MB, 95 MB RSS.
- [x] A small read API for fighters, fights, seasons and search; the chain or contract stays the source of truth.
  `qdojo combat api` (`combat/api.py`, [api.md](../../docs/api.md) §3.2), which also serves the static export and
  replaces the `http.server` unit. Evidence: `tests/combat/test_api.py` (contract, pagination, errors, CORS, ETag,
  static paths); fight and replay documents equal the exporter's.
- [x] The site reads the API with the static export as fallback.
  Fighter pages (full career, paginated, full-career scouting on request), results, leaderboard and pruned fights.
  Evidence: `apps/web/tests/e2e/api-run.cjs` against the live-copy database: a fighter with 956 fights, page 20
  reaching fight #4 (the export keeps #5024 on), and `run.cjs` 28/28 on the static fallback.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
