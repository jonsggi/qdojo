# AUD-018 — House economics do not close

- **Status:** Mitigated in the demo arena (new arenas); production values still need measured Qubic costs
- **Priority:** P1 — paid launch gate
- **Type:** Economics
- **Evidence:** Over 34.8 h simulated execution fees burned 1.06 M QU against 361 k of rake (216 k to the house) plus 140 k sponsorship: about −986 k
- **Scope:** `combat/economics`, fee model, `docs/economics-report.md`, `docs/matchmaking.md`

## Finding

At a 1,000 QU stake a ranked fight costs about 180–200 QU in execution fees against 100 QU of rake ([simulation audit](../reports/2026-09-25-simulation-audit.md) §2.1).

## Acceptance criteria

- [x] Re-run the economics including execution cost and choose tiers, rake and entry fees so the house at least breaks even per fight. `combat-economics.py` now includes the simulated fee model and a break-even table; the demo profile uses 5,000/20,000 QU tiers, 500 bps ranked rake, a 1,000 bps cup fee profile and tier-scaled duel stakes and cup entries. Demo arena, 20,000 ticks, same lineup and seed: house P&L per fight **−160.8 → +91.6 QU**, every mode positive (ranked +85.1, cup +38.7 after sponsorship, duel +21.5); 10,000 ticks: −156.5 → +84.5 ([economics report](../../docs/economics-report.md)).
- [ ] Measure real Qubic execution costs before fixing values. Open: the fee model is a candidate. The break-even stake scales linearly with it (about 3,100 QU at 187 QU per fight).
- [x] Document the target (house margin, player expected value) in `docs/product-decisions.md` ("Demo arena economics (2026-09-26)").

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
