# AUD-019 — Honest players lose money; cups and duels were farmed

- **Status:** Open (partly addressed by AUD-014)
- **Priority:** P1 — fairness / outside stakes
- **Type:** Economics / competition design
- **Evidence:** An average honest bot loses about 70–100 QU per 1,000 QU fight; oni took 25 of 27 cups (+388 k), tengu went 138–5 in duels (+241 k)
- **Scope:** Cup and duel rules, demo lineup, bot accept filters

## Finding

Auto-accepted duels, cups without the strong ranked bots and sponsorship capture let fixed scripts farm events ([simulation audit](../reports/2026-09-25-simulation-audit.md) §2.2–2.4).

## Acceptance criteria

- [ ] Re-measure after AUD-014 now that history bots adapt.
- [ ] Duel accept filters (rating gap, stake) and wider cup entry.
- [ ] Cap sponsorship capture; publish player expected value per tier.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
