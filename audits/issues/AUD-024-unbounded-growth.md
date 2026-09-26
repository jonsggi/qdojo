# AUD-024 — index.json and restart time grow without bound

- **Status:** Open
- **Priority:** P2 — operations
- **Type:** Export / operations
- **Evidence:** index.json embeds every fighter's full ownership history; a restart replays the whole journal (about 90–130 s, growing about 3 s per hour)
- **Scope:** `combat/export.py`, `combat/live.py`, contract hot state

## Finding

Both grow with runtime and will eventually make restarts and page loads slow ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.2, §1.6).

## Acceptance criteria

- [ ] Move ownership history out of index.json (per-fighter or paginated).
- [ ] Snapshot state so restarts do not replay the full journal; prune finished fights, contests and offers from hot state.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
