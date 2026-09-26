# AUD-025 — Tests accepted overdue live fights

- **Status:** Open
- **Priority:** P1 — regression safety
- **Type:** Testing
- **Evidence:** `apps/web/tests/e2e/run.cjs` accepted "DEADLINE PASSED" as a pass, which hid AUD-011; the soak never runs the exporter
- **Scope:** `apps/web/tests/e2e/run.cjs`, `scripts/combat-soak.py`

## Finding

The exporter bug went unnoticed because no test asserted that published fights reflect the chain ([simulation audit](../reports/2026-09-25-simulation-audit.md) §6).

## Acceptance criteria

- [ ] An invariant: no published fight may be overdue by more than N ticks.
- [ ] A soak phase that exports every N ticks and asserts every DONE fight's published file is final.
- [ ] A bot-level assertion that no reveal is rejected with BAD_PLAN.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
