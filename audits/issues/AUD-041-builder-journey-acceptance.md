# AUD-041 — Test the published builder journey against the active ruleset

- **Status:** Open
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

- [ ] Create a deterministic local acceptance arena using the intended release
  ruleset and the real outside-entry/read API path, with fake funds.
- [ ] Follow the published starter path: obtain the advertised planner, doctor/train,
  evaluate it, register/join, complete a fight, fetch the replay and verify it.
- [ ] Include an opponent that actually executes LAST_STAND and FEINT under
  candidate 3; reject unexpected starter errors or fallback use.
- [ ] Assert agreement between the intended manifest, documented commands, training,
  evaluation and replay ruleset digests.
- [ ] Exercise both the repository and downloadable planner distribution paths.
- [ ] Cover closed-entry messaging and malformed/tampered replay behavior.
- [ ] Add the completed-practice share round trip once AUD-034 is implemented.
- [ ] Preserve historical replay checks alongside current-ruleset coverage.
- [ ] Make the release invocation fail clearly when a required runtime/browser is
  unavailable; an explicit optional local skip must not look like release acceptance.
- [ ] Run locally without contacting the production arena, external LLM providers
  or real funds, and document how the supported release ruleset is selected.

## Related work

Depends on [AUD-029](AUD-029-starter-planner-new-moves.md),
[AUD-030](AUD-030-onboarding-ruleset-consistency.md) and
[AUD-031](AUD-031-custom-planner-benchmark.md) for a passing builder flow.
Practice sharing is [AUD-034](AUD-034-share-completed-practice-fight.md).
The test complements the existing engine, contract parity and browser suites.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
