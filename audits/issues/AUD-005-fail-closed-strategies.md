# AUD-005 — Fail closed when an entry strategy crashes or returns invalid output

- **Status:** Open
- **Priority:** P1 — resolve before unattended third-party bot use
- **Type:** Spending safety / API behavior change
- **Evidence:** Failure decision reproduced locally; behavior is currently documented, not an accidental undocumented deviation
- **Scope:** `packages/qdojo/src/qdojo/bot.py:56–77`, `:111–172`; `docs/api.md:105–121`

## Finding

`_strategy_says_enter()` returns true after exceptions, timeouts, missing output
and invalid JSON. It accepts any decoded result except an explicit boolean
`enter: false`, and does not require a successful subprocess exit code. This
bypasses the very strategy a user may rely on to limit exposure.

`--max-stake` limits an individual round's fee, not cumulative spending across
rounds or all pending submissions. `_can_pay()` does protect against an unknown
live balance; that protection should be preserved.

## Reproduction

Run `uv run python audits/probes/financial_findings.py`.
`fail_open_strategy()` executes a strategy that immediately exits 1. The decision
returns true and logs “entering anyway.” This probe does not send a transaction.
In `Bot.step`, a true decision can lead to a paid ENTER/COMMIT if the other guards
permit it.

## Impact

A broken risk-control program may cause repeated unwanted entries instead of
stopping exposure. An intentionally declining strategy and a broken strategy
should not have opposite money-safety defaults.

## Acceptance criteria

- [ ] Require exit code 0 and a schema-valid `{"enter": true}` to authorize entry when a strategy is configured.
- [ ] Timeout, crash, missing output, invalid JSON and wrong types cause no paid entry; emit an actionable reason.
- [ ] Define no-strategy behavior separately and document migration from the current fail-open contract.
- [ ] Continue required reveals for already-committed rounds even when future entry decisions fail.
- [ ] Add fake-chain tests for every failure class in lobby and non-lobby rounds, asserting no new paid submission.
- [ ] Provide an independently enforced session/daily budget or create a linked spending-budget issue; account for pending spends across restart, not just the last observed balance.

**Note:** If legacy fail-open operation must remain available, require explicit opt-in with a clear spending warning; it should not be the safe default.
