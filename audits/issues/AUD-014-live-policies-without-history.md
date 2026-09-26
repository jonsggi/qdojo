# AUD-014 — History-based policies played blind in the live arena

- **Status:** Fixed in `0918949` (deployed 2026-09-25)
- **Priority:** P1 — game integrity
- **Type:** Bot correctness
- **Evidence:** repeat-last-winner repeated a plan 0 times in 1,433 rounds; reader-v1 played like mixed-v1; one fixed script won 25 of 27 cups
- **Scope:** `combat/bot.py` (`policy_chooser`)

## Finding

The live adapter never passed earlier rounds, so reader-v1, repeat-last-winner and search-v1 could not adapt ([simulation audit](../reports/2026-09-25-simulation-audit.md) §3.1).

## Acceptance criteria

- [x] `policy_chooser` rebuilds prior rounds from the observation.
- [x] Test: a history-based policy changes its plan on prior rounds in live mode.
- [x] Soak: repeat-last-winner repeats 79 of 79; reader-v1 goes from 14–27 to 27–21.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
