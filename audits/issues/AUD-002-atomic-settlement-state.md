# AUD-002 — Make settlement closeout atomic and recoverable

- **Status:** Open
- **Priority:** P0 — block reopening real-money rounds until resolved
- **Type:** Accounting / crash consistency
- **Evidence:** Reproduced carry inconsistency on FakeChain
- **Scope:** `packages/qdojo/src/qdojo/house.py:387–451` (`settle`), `:254–288` (`void`), `:35–41` (`_write`)

## Finding

`settle()` writes the settlement document, then terminal round status, then belt
state, bond state, and aggregate carry/shareholder/dev state as separate file
operations. If the process fails after terminal status but before aggregate state
is persisted, the next call returns the settlement immediately and never repairs
the remaining state. `void()` similarly writes terminal status before carry.

Atomic rename of one JSON file does not make this multi-file transaction atomic.
The writer also does not fsync data or the parent directory; power-loss durability
needs an explicit design in addition to process-crash recovery.

## Reproduction

Run `uv run python audits/probes/financial_findings.py`.
`partial_closeout()` creates a fake empty round with a fixed 1,000-QU seed, then
injects an `OSError` at the final aggregate state write. After restart:

- round status is `settled`;
- the settlement records `carry: 1000`;
- aggregate state still records `carry: 0`;
- re-running settlement returns without repair.

This reproduces carry inconsistency. Bond/belt/shareholder inconsistencies follow
from the write ordering but need their own failure-injection tests.

## Impact

The next round can use incorrect carry or rank state; custody liabilities and
shareholder accounting may disagree with published settlements. Repeated partial
closeouts can also complicate operator recovery.

## Acceptance criteria

- [ ] Persist closeout in one durable transaction (e.g. SQLite), or a journal with an idempotent per-round application marker and deterministic recovery.
- [ ] Resume or reconcile partially applied closeouts before exposing terminal status or starting another round.
- [ ] Apply carry, bonds, belts, shareholder pool and developer totals exactly once.
- [ ] Inject failures at every persistence boundary for settled and void rounds; restart converges to the same document/state as an uninterrupted run.
- [ ] Reconcile aggregate state against recorded settlement events without re-sending payouts.
- [ ] Specify fsync/durability guarantees and a backup/recovery procedure.

**Related:** [AUD-001](AUD-001-ambiguous-payout-submission.md), [AUD-003](AUD-003-confirm-settle-anchor.md), [AUD-004](AUD-004-single-writer-state.md).
