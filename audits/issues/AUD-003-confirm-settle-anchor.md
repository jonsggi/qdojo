# AUD-003 — Confirm SETTLE inclusion before declaring the round fully settled

- **Status:** Open
- **Priority:** P1 — resolve before public real-money operation
- **Type:** Protocol correctness / evidence publication
- **Evidence:** Reproduced on FakeChain with a dropped SETTLE message
- **Scope:** `packages/qdojo/src/qdojo/house.py:278–288`, `:420–451`; `packages/qdojo/tests/test_house_and_bot.py:test_full_round_two_bots_one_wins`

## Finding

Payouts are confirmed, but the final SETTLE message is only sent. Its scheduled
tick is stored as `settle_tick`, and the round becomes `settled`/`void` without
calling `chain.confirm()` on the SETTLE transaction. A retry of a terminal round
returns the document immediately. The happy-path test advances the fake chain
for SETTLE only *after* asserting terminal status.

## Reproduction

Run `uv run python audits/probes/financial_findings.py`.
`unconfirmed_closeout()` settles a no-payout round while dropping the next send
(SETTLE). Once the scheduled tick has passed, confirmation is false, but the round
remains terminal and a repeated settle does not repair the missing anchor.

## Impact

The web export claims a completed round although its published settlement hash
may never have been anchored on chain. A scheduled tick can be mistaken for a
confirmed tick. This does not show that already confirmed payouts failed.

## Acceptance criteria

- [ ] Distinguish payouts complete, anchor pending, anchor confirmed and anchor failed/unknown in persistent state and exports.
- [ ] Confirm the exact SETTLE ID in its tick before representing the round as fully anchored.
- [ ] Separate scheduled and confirmed tick fields, or document an equivalent unambiguous schema.
- [ ] Resume anchor publication after restart without re-sending confirmed payouts or double-applying aggregate state.
- [ ] Test dropped sends, `Unknown`, delayed confirmation and restart for both settled and void rounds.
- [ ] Keep failed/pending evidence visible to spectators rather than silently labeling it fully complete.

**Dependencies:** Coordinate the transaction intent and recovery design with [AUD-001](AUD-001-ambiguous-payout-submission.md) and [AUD-002](AUD-002-atomic-settlement-state.md).
