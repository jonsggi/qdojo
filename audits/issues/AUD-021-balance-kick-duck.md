# AUD-021 — Kick dominates; duck and throw are near useless

- **Status:** Open
- **Priority:** P2 — strategic depth
- **Type:** Rules balance
- **Evidence:** Net HP per beat in the live field: KICK +7.5, DUCK −4.8, THROW −0.1; power and opening add about 4 HP per fight
- **Scope:** `docs/combat.md`, `docs/combat-v1.json` (a new ruleset digest)

## Finding

Measured in a field where half the bots played blind (AUD-014); may shift once history bots adapt ([simulation audit](../reports/2026-09-25-simulation-audit.md) §3.2–3.3).

## Acceptance criteria

- [ ] Re-measure with the fixed field.
- [ ] If it persists, trial a candidate-2 ruleset (kick cost or damage, duck counter, bigger power/opening) behind a new digest and the full model.md campaign.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
