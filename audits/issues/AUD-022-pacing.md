# AUD-022 — A ranked fight takes twice the target time

- **Status:** Open
- **Priority:** P2 — spectator experience
- **Type:** Timing
- **Evidence:** 123 s per ranked fight against a 60 s median target; each round is about 42 s, mostly the fixed 24-tick commit window
- **Scope:** Demo timing profile, `docs/model.md` §4

## Finding

Spectators wait about 40 s per round for six beats that land at once ([simulation audit](../reports/2026-09-25-simulation-audit.md) §4.1). The site now plays rounds back beat by beat.

## Acceptance criteria

- [ ] A demo timing profile (for example commit 8 / reveal 6 ticks).
- [ ] Per-beat playback during the next commit window (site side done).

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
