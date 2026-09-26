# AUD-020 — Ratings do not converge and season titles are noisy

- **Status:** Open
- **Priority:** P2 — competition quality
- **Type:** Matchmaking / ratings
- **Evidence:** Rating spread widened 545 to 1,300 points; the top two bots mostly fought each other (210 times) and failed the distinct-opponent rule; a season went to a 754-rated fighter
- **Scope:** `docs/competition.md`, `docs/matchmaking.md`, demo profile

## Finding

Narrow rating windows in a small population and the four-distinct-opponent rule block the best fighters from qualifying ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.5).

## Acceptance criteria

- [ ] Scale season qualification to population size.
- [ ] Review matchmaking windows so the top pair does not dominate its own pairings.
- [ ] Re-measure spread after AUD-014.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
