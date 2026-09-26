# AUD-018 — House economics do not close

- **Status:** Open
- **Priority:** P1 — paid launch gate
- **Type:** Economics
- **Evidence:** Over 34.8 h simulated execution fees burned 1.06 M QU against 361 k of rake (216 k to the house) plus 140 k sponsorship: about −986 k
- **Scope:** `combat/economics`, fee model, `docs/economics-report.md`, `docs/matchmaking.md`

## Finding

At a 1,000 QU stake a ranked fight costs about 180–200 QU in execution fees against 100 QU of rake ([simulation audit](../reports/2026-09-25-simulation-audit.md) §2.1).

## Acceptance criteria

- [ ] Re-run the economics including execution cost and choose tiers, rake and entry fees so the house at least breaks even per fight.
- [ ] Measure real Qubic execution costs before fixing values.
- [ ] Document the target (house margin, player expected value) in `docs/product-decisions.md`.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
