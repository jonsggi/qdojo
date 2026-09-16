# AUD-004 — Enforce single-writer ownership of house and bot state

- **Status:** Open
- **Priority:** P1 — resolve before unattended real-money operation
- **Type:** Concurrency / operational safety
- **Evidence:** Code-reviewed risk; concurrent-process reproduction not yet run
- **Scope:** `packages/qdojo/src/qdojo/house.py:35–41`, `House.settle`, `House.collect`; `packages/qdojo/src/qdojo/bot.py:32–54`, `Bot.step`

## Finding

House and bot state uses read/modify/write JSON and shared `.tmp` paths. No
state-directory process lock or transactional compare-and-swap was found in the
reviewed package and scripts. Two CLI/supervisor processes using one state
location can read the same unprocessed ledger entry and both send before either
persists its result. Atomic replacement of a file does not serialize the business
operation. Shared temporary names also allow competing writers to interfere.

This is a concurrency risk inferred from code, not a confirmed production race.
The phase-zero closeout says the supervisors are stopped; do not start them merely
to reproduce this issue.

## Suggested reproduction

Use two processes and a fake signing adapter with a barrier after both read the
same ledger entry. Release both together and record submissions. Repeat for two
bot instances entering the same round and for concurrent collect/state updates.
Use temporary directories only.

## Acceptance criteria

- [ ] Acquire an exclusive state-directory lock covering each full mutation/send workflow, or use transactional intent claiming with equivalent guarantees.
- [ ] A second operator process fails clearly or waits safely; it must not submit transactions while another owns the state.
- [ ] Apply protection to house commands, bot run, and supervisor paths sharing state.
- [ ] Test competing payouts, entries, collector state updates, and lock release after process death.
- [ ] Ensure export/read paths see consistent snapshots without sharing mutable `.tmp` files.
- [ ] Document supported process topology and recovery without unsafe stale-lock deletion.

**Related:** [AUD-001](AUD-001-ambiguous-payout-submission.md), [AUD-002](AUD-002-atomic-settlement-state.md). A lock alone does not solve ambiguous network outcomes or multi-file crash recovery.
