# AUD-022 — A ranked fight takes twice the target time

- **Status:** Mitigated (timing wiring 67f10c1; demo timing 9/8 in profile `demo-c2`; the live arena runs it once the orchestrator starts a `demo-c2` arena)
- **Priority:** P2 — spectator experience
- **Type:** Timing
- **Evidence:** 123 s per ranked fight against a 60 s median target; each round is about 42 s, mostly the fixed 24-tick commit window
- **Scope:** Demo timing profile, `docs/model.md` §4

## Finding

Spectators wait about 40 s per round for six beats that land at once ([simulation audit](../reports/2026-09-25-simulation-audit.md) §4.1). The site now plays rounds back beat by beat.

## Acceptance criteria

- [x] A demo timing profile: devnet profile `demo-c2`, timing profile 1 = **commit 9 / reveal 8 ticks** (9/6 forfeited 6% of fights: see docs/model.md §4)
  (`combat/devnet.py`, `DEMO_C2_TIMING`, through the same `timing` profile value and devnet.json record as `DEMO_TIMING`; `qdojo combat live --timing C,R` still overrides it for a new arena). Measured on the simulated chain with candidate 2:
  ranked median 37 ticks = **55.5 s**, p95 39 ticks = 58.5 s (104 fights); on the 60-stamina trial 10/6 gave 60/63 s and 8/6 51/54 s.
  The live 24/12 arena measures a median 80 ticks = 120 s. Details: [model.md §4](../../docs/model.md#4-timing-and-compute).
  LLM planners need a budget of at most about 7 s under this window (lineup `budget_ms`, `--timeout`).
- [x] Per-beat playback during the next commit window (site side done; 6 × 600 ms fits in 13.5 s).

## Resolution

The profile also selects combat-v1 candidate 2 (AUD-021), because a devnet's
ruleset and timing are fixed when it is created: switching means a fresh arena
directory, not a change to the running one: `qdojo combat live --profile demo-c2`.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
