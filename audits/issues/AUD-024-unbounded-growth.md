# AUD-024 — index.json and restart time grow without bound

- **Status:** Fixed in `67f10c1` (not yet deployed)
- **Priority:** P2 — operations
- **Type:** Export / operations
- **Evidence:** index.json embeds every fighter's full ownership history; a restart replays the whole journal (about 90–130 s, growing about 3 s per hour)
- **Scope:** `combat/export.py`, `combat/live.py`, contract hot state

## Finding

Both grow with runtime and will eventually make restarts and page loads slow ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.2, §1.6).

## Acceptance criteria

- [x] Move ownership history out of index.json (per-fighter or paginated). index.json keeps each fighter's last 4 transfers plus a count (`export.index_deployment`); `fighters/<id>.json` has the full history. On the live index of 2026-09-26 (65 history entries): 27,314 → 21,455 bytes, and no longer growing with sales.
- [x] Snapshot state so restarts do not replay the full journal; prune finished fights, contests and offers from hot state. `store.compact` every 600 ticks (scouting, records, fighter pages and late budget settlement stay exact: `test_compaction_is_transparent_to_the_arena` runs the same seed with and without compaction and gets the same event digest, ledger and ratings). A verified snapshot every 1,200 ticks with fallback to the previous one and then to a full replay (`devnet.py`); every replay checks the `digest` checkpoints it crosses.

Measured with `scripts/combat-restart-bench.py` on a copy of `~/.qdojo/combat/arena` (107 MB journal, 199,638 records, tick 107,940), CPU seconds (wall time was inflated by host load):

| Restart | CPU s | Wall s | Fights in memory | Peak RSS |
|---|---:|---:|---:|---:|
| Before: full replay | 286.5 | 1,204 | 5,235 (+4,408 contests, 9,318 offers, 199,638 journal records) | 392 MB |
| After: full replay with compaction (first restart after a deploy) | 28.0 | 40.8 | 680 (459 contests, 749 offers, 0 journal records) | 457 MB |
| After: from a snapshot (2.0 MB) | 0.3 | 0.3 | same state; same event digest | — |

Also bounded: bot budget files drop settled spends of past days; `pair_starts` of past epochs, fault counts older than 8 epochs and season stats older than 6 seasons are dropped. The journal itself still grows (about 2.5 MB/h); it is the audit trail and is only read once per code deploy.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
