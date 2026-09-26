# AUD-025 — Tests accepted overdue live fights

- **Status:** Fixed in `67f10c1` (not yet deployed)
- **Priority:** P1 — regression safety
- **Type:** Testing
- **Evidence:** `apps/web/tests/e2e/run.cjs` accepted "DEADLINE PASSED" as a pass, which hid AUD-011; the soak never runs the exporter
- **Scope:** `apps/web/tests/e2e/run.cjs`, `scripts/combat-soak.py`

## Finding

The exporter bug went unnoticed because no test asserted that published fights reflect the chain ([simulation audit](../reports/2026-09-25-simulation-audit.md) §6).

## Acceptance criteria

- [x] An invariant: no published fight may be overdue by more than N ticks. `invariants.check_export(contract, root, slack)` also requires every fight the contract finished before the export to be published final, and results.json and index.json to agree; `live.run` checks every tenth export and logs `export invariant: …`. `test_check_export_catches_a_fight_frozen_mid_round` reinstates the AUD-011 exporter bug and requires the invariant to catch it.
- [x] A soak phase that exports every N ticks and asserts every DONE fight's published file is final: `combat-soak.py` steady phase (default 2,000 ticks, export every 6, each export checked); 0 problems.
- [x] A bot-level assertion that no reveal is rejected with BAD_PLAN: bots count final rejections (`Bot.rejected`); the steady phase runs two power-reusing LLM stand-ins (`"stub": "power-reuse"`) and fails on any BAD_PLAN, or if no spent power slot was ever stripped.
- [x] `apps/web/tests/e2e/run.cjs` fails on "DEADLINE PASSED" on any live card and checks the sample export against itself (`export-consistency`); verified to fail on a tampered copy.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
