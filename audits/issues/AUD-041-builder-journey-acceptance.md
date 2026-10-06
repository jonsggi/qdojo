# AUD-041 — Test the published builder journey against the active ruleset

- **Status:** Fixed in 0b84af43: tests/combat/test_builder_journey.py (in `make test`) and `make release-check`
- **Priority:** P1 — regression protection for onboarding
- **Type:** Integration / acceptance testing
- **Scope:** tests/test_docs_commands.py, combat integration tests, apps/web/tests/e2e/run.cjs, release checks

## Finding and impact

The review's 34 browser steps and focused Python checks passed while the
advertised starter crashed on candidate-3 moves and the onboarding commands
pointed at other rulesets. The browser suite uses a recorded candidate-1 sample;
published-command tests establish parser acceptance, not completion of the
builder journey.

Existing tests have value, but do not enforce the promise that the public
instructions work together for the current arena rules.

## Acceptance criteria

- [x] Create a deterministic local acceptance arena using the intended release
  ruleset and the real outside-entry/read API path, with fake funds. *Evidence:* a demo-c3 `live.Arena` (deterministic, fake QU) with the join inbox, `JoinService` and the real read API on 127.0.0.1.
- [x] Follow the published starter path: obtain the advertised planner, doctor/train,
  evaluate it, register/join, complete a fight, fetch the replay and verify it. *Evidence:* doctor --arena, evaluate, `qdojo combat join --register-only`, a ranked fight by the starter through `RemoteClient` and `Bot` (the components `combat join` runs; ticks are held while the planner decides instead of racing a clock), the replay fetched over HTTP and verified by `combat replay URL`.
- [x] Include an opponent that actually executes LAST_STAND and FEINT under
  candidate 3; reject unexpected starter errors or fallback use. *Evidence:* the house bots are `stander` and `feinter`; any planner fallback or adjusted plan fails the test. A starter that crashes on FEINT fails it (checked by mutation).
- [x] Assert agreement between the intended manifest, documented commands, training,
  evaluation and replay ruleset digests. *Evidence:* arena manifest, join info, CLI output, evaluation JSON, practice replay and arena replay all carry the `PUBLIC_ARENA` digest; the quickstart passes no `--ruleset`.
- [x] Exercise both the repository and downloadable planner distribution paths. *Evidence:* train and replay run with both copies; the journey runs the site download.
- [x] Cover closed-entry messaging and malformed/tampered replay behavior. *Evidence:* `test_closed_entry_says_so_and_creates_nothing` (doctor WARN, join refuses, no key written); a tampered arena replay is refused by `combat replay`.
- [x] Add the completed-practice share round trip once AUD-034 is implemented. *Evidence:* the browser suite's `practice-share` step (AUD-034).
- [x] Preserve historical replay checks alongside current-ruleset coverage. *Evidence:* the existing parity and replay tests still run on candidates 1 and 2.
- [x] Make the release invocation fail clearly when a required runtime/browser is
  unavailable; an explicit optional local skip must not look like release acceptance. *Evidence:* `make release-check` sets `QDOJO_E2E_REQUIRED=1`: without Playwright or Chromium the browser suite exits 3 instead of skipping, and refuses `QDOJO_E2E_ONLY`.
- [x] Run locally without contacting the production arena, external LLM providers
  or real funds, and document how the supported release ruleset is selected. *Evidence:* 127.0.0.1 only, deterministic policies, fake QU; the release ruleset is `PUBLIC_ARENA` (docs/operations.md §7).

## Related work

Depends on [AUD-029](AUD-029-starter-planner-new-moves.md),
[AUD-030](AUD-030-onboarding-ruleset-consistency.md) and
[AUD-031](AUD-031-custom-planner-benchmark.md) for a passing builder flow.
Practice sharing is [AUD-034](AUD-034-share-completed-practice-fight.md).
The test complements the existing engine, contract parity and browser suites.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
