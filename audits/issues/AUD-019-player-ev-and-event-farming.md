# AUD-019 — Honest players lose money; cups and duels were farmed

- **Status:** Mitigated in `f27a972` (not yet deployed); see the economics report
- **Priority:** P1 — fairness / outside stakes
- **Type:** Economics / competition design
- **Evidence:** An average honest bot loses about 70–100 QU per 1,000 QU fight; oni took 25 of 27 cups (+388 k), tengu went 138–5 in duels (+241 k)
- **Scope:** Cup and duel rules, demo lineup, bot accept filters

## Finding

Auto-accepted duels, cups without the strong ranked bots and sponsorship capture let fixed scripts farm events ([simulation audit](../reports/2026-09-25-simulation-audit.md) §2.2–2.4).

## Acceptance criteria

- [x] Re-measure after AUD-014 now that history bots adapt: `scripts/combat-arena-metrics.py`. Before these changes (history fixed), 10,000 ticks: strong bots +196 QU per 1,000 QU fight, average −78, weak −220; tengu still won 21 of 23 duel series (91%, 66% of all series wins).
- [x] Duel accept filters (rating gap, stake) and wider cup entry: `Budget.duel_max_stake`, `duel_max_rating_gap`, and a head-to-head rule from the bot's own series history, applied both when accepting and when challenging (`Bot.challenge`: the arena picks a pair, the challenger's bot decides and records the series; before, the arena sent challenges for bots outside their budgets, so a weak challenger never learned); ranked bots enter cups by default. 20,000 ticks, same seed: duel series 62 → 18 (weak bots stop playing the fighter that beats them), tengu's duel winnings 56 → 15 tier-stakes; cups now go to strong ranked bots (kappa 4 of 6, an adaptive search bot).
- [x] Cap sponsorship capture; publish player expected value per tier. No sponsorship while one fighter won more than 2 of the last 6 sponsored cups (`Arena.sponsorship`); `economics.json` publishes per-tier EV by win share, the break-even win share (0.526) and measured net per ranked fight by rating band. 20,000 ticks after: strong bots +1,180 per 5,000 QU fight (+23.6% of stake, before +18.2%), average −272 (−5.4%, before −6.0%), weak −1,123 (−22%); the sponsorship cap withheld sponsorship for 2 of 6 cups.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
