# AUD-001 — Persist payout submission identity before broadcasting

- **Status:** Open
- **Priority:** P0 — block reopening real-money rounds until resolved
- **Type:** Financial correctness / crash recovery
- **Evidence:** Reproduced on FakeChain; not evidence of a historical live loss
- **Scope:** `packages/qdojo/src/qdojo/house.py:453–473` (`_pay_ledger`), `packages/qdojo/src/qdojo/chain/cli.py:81–89` (`send`)

## Finding

The ledger is written before payout processing, but its transaction ID and tick
are recorded **after** `chain.send()` returns. A transaction can be accepted and
even land while the receipt is lost (CLI timeout, connection failure, parse
failure, process death, or a failure writing the returned receipt). The persisted
entry still has `tx: null`. Restarting settlement then sends a new transaction.

The CLI's missing-receipt error says to treat the transaction as NOT sent. Lack
of a receipt cannot establish non-inclusion. Existing lost-send coverage exercises
a recorded transaction that provably did not land, not an accepted send whose
receipt was lost.

## Reproduction

Run `uv run python audits/probes/financial_findings.py` from the repo root.
`lost_receipt()` persists a 1,000-QU payout, queues its transaction and raises
`Unknown` before returning a receipt. After the first transfer lands, a fresh
House instance retries the persisted ledger. The fake recipient receives 2,000 QU.
No real keys, endpoints, or transfers are used.

## Impact

A single ledger liability may be paid twice after an ambiguous submission. The
same prepare/broadcast boundary should be reviewed for publish, lobby, SETTLE,
and bot messages, without assuming all those paths share the same failure mode.

## Acceptance criteria

- [ ] Introduce a prepare/sign → durably persist immutable tx ID, bytes, tick and intent → broadcast interface, or another design that can unambiguously reconcile accepted submissions.
- [ ] On ambiguous submission, block replacement transactions until chain evidence establishes non-inclusion; a timeout is never proof of failure.
- [ ] Re-broadcast the same signed transaction where appropriate, rather than creating a new payable intent.
- [ ] Test acceptance followed by lost receipt, process restart, and receipt-write failure. Recipient is credited at most once.
- [ ] Retain coverage for confirmed absence and safe retry, including schedule expiry.
- [ ] Correct the missing-receipt message and document operator recovery without manual ledger deletion.

**Related:** [AUD-002](AUD-002-atomic-settlement-state.md), [AUD-003](AUD-003-confirm-settle-anchor.md), [AUD-004](AUD-004-single-writer-state.md).
