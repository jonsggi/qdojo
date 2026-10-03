# AUD-038 — Validate strategic learning and replay readability with outside builders

- **Status:** Open (research proposal)
- **Priority:** P1 — evidence for the next rules decision
- **Type:** Product research / game balance
- **Scope:** docs/model.md, validation-status.md, beta observations, replay and planner experiments

## Finding and impact

The candidate-3 report passes 11 strategic gates in its declared policy pool.
That establishes useful measured properties, but it does not measure human
understanding, enjoyment, adaptation to outside strategies or a lasting metagame.

LAST STAND yields more comebacks in the tested field. We still need to know
whether players understand its cause and counterplay. FEINT likewise needs
readability testing. Adding moves during the experiment would obscure what
participants learned.

## Acceptance criteria

- [ ] Pin the ruleset and policy versions for a time-bounded beta cohort; record
  any necessary correction and separate results before and after it.
- [ ] Exercise the existing docs/model.md readability target: reviewers can identify
  causes in at least 8 of 10 sampled decisive exchanges using the replay UI.
- [ ] Include LAST STAND, FEINT/guard breaks, resource failures, simultaneous trades,
  forfeits and reduced-motion examples.
- [ ] Observe independent builders implementing, revising and countering strategies
  using the public tooling; distinguish independent approaches from starter copies.
- [ ] Measure adaptation to a changing opponent and the cost of stale assumptions,
  which remain absent from the candidate-3 campaign.
- [ ] Record session feedback on clarity, perceived counterplay and desire to replay,
  with participant counts and failed cases.
- [ ] Publish the findings and update validation status without treating the 11/11
  simulation result as proof of human engagement or universal balance.
- [ ] Make the next rules decision from these findings; preserve versioned artifacts
  and old replays if a new candidate is warranted.

## Related work

Extends [AUD-021](AUD-021-balance-kick-duck.md), rather than reopening its original
kick-dominance claim. Coordinate the cohort with
[AUD-039](AUD-039-builder-beta-and-commercial-evidence.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
