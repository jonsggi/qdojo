# AUD-020 — Ratings do not converge and season titles are noisy

- **Status:** Mitigated (not yet deployed); see the economics report
- **Priority:** P2 — competition quality
- **Type:** Matchmaking / ratings
- **Evidence:** Rating spread widened 545 to 1,300 points; the top two bots mostly fought each other (210 times) and failed the distinct-opponent rule; a season went to a 754-rated fighter
- **Scope:** `docs/competition.md`, `docs/matchmaking.md`, demo profile

## Finding

Narrow rating windows in a small population and the four-distinct-opponent rule block the best fighters from qualifying ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.5).

## Acceptance criteria

- [x] Scale season qualification to population size: `contract.Qualification(scale=True)` for the demo (distinct opponents 20% of the season's field, 2..4; defeated one less, 1..3), a query-side rule published in `seasons.json`; the spec rule stays the default.
- [x] Review matchmaking windows so the top pair does not dominate its own pairings: after AUD-014 the top-rated pair's meetings were 15% of their fights in 10,000 ticks (the most common pair 5% of ranked fights), not the audit's 210 meetings. The demo profile's pair cap goes from 6 to 3 rated starts per epoch for new arenas; the 100..200 rating window is contract spec (and in the C++ port), left unchanged.
- [x] Re-measure spread after AUD-014: 10,000 ticks, range 552 before, 428 after, mean drift about 13 rating points per 1,000 ticks in the last third; season 1 went to the top-rated fighter in both runs. 20,000-tick pair in the [economics report](../../docs/economics-report.md).

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
