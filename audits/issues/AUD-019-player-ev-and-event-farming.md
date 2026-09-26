# AUD-019 — Honest players lose money; cups and duels were farmed

- **Status:** Mitigated (not yet deployed); see the economics report
- **Priority:** P1 — fairness / outside stakes
- **Type:** Economics / competition design
- **Evidence:** An average honest bot loses about 70–100 QU per 1,000 QU fight; oni took 25 of 27 cups (+388 k), tengu went 138–5 in duels (+241 k)
- **Scope:** Cup and duel rules, demo lineup, bot accept filters

## Finding

Auto-accepted duels, cups without the strong ranked bots and sponsorship capture let fixed scripts farm events ([simulation audit](../reports/2026-09-25-simulation-audit.md) §2.2–2.4).

## Acceptance criteria

- [x] Re-measure after AUD-014 now that history bots adapt: `scripts/combat-arena-metrics.py`. Before these changes (history fixed), 10,000 ticks: strong bots +196 QU per 1,000 QU fight, average −78, weak −220; tengu still won 21 of 23 duel series (91%, 66% of all series wins).
- [x] Duel accept filters (rating gap, stake) and wider cup entry: `Budget.duel_max_stake`, `duel_max_rating_gap`, and a head-to-head rule from the bot's own series history; ranked bots enter cups by default. After, same seed: tengu 13 of 17 series (45% of series wins); the three cups went to kappa (2) and tanuki, strong ranked bots that were not cup-enabled before.
- [x] Cap sponsorship capture; publish player expected value per tier. No sponsorship while one fighter won more than 2 of the last 6 sponsored cups (`Arena.sponsorship`); `economics.json` publishes per-tier EV by win share, the break-even win share (0.526) and measured net per ranked fight by rating band. After, same seed: strong bots +780 per 5,000 QU fight (+15.6% of stake), average −265 (−5.3%), weak −1,071 (−21%).

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
