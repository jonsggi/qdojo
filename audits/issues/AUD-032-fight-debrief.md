# AUD-032 — Turn fight results into an actionable debrief

- **Status:** Open (product proposal)
- **Priority:** P1 — learning and repeat play
- **Type:** UX / feature
- **Scope:** combat/logic.js, combat/app.js practice and replay results, combat/training.py explanations

## Finding and impact

The engine and UI already expose beat explanations and hindsight alternatives.
Users still have to inspect traces to decide which moments mattered and what to
change. A result should help a new player move from losing to trying a better plan.

The review proposes a short debrief that surfaces existing evidence; a new
generative explanation service is not required.

## Acceptance criteria

- [ ] Show a concise post-fight summary with a small number of decisive or costly
  exchanges and links that seek to the relevant replay beats.
- [ ] Explain observed causes in plain language, including exhausted attacks,
  punished recovery, wasted power, and candidate-3 interactions when relevant.
- [ ] Suggest a specific next experiment or practice opponent from those observations.
- [ ] Label alternatives as hindsight against the recorded opposing move; never
  promise that a different plan would force the same opponent response.
- [ ] Separate combat lessons from timeouts/forfeits and never invent decisive
  beats for an unfinished or unplayed round.
- [ ] Preserve access to full traces and identical information with motion disabled.
- [ ] Validate with recorded examples and new players: can they identify a relevant
  mistake and name a change they intend to try?

## Related work

Pair with [AUD-033](AUD-033-practice-progress.md) for follow-through and
[AUD-038](AUD-038-human-strategy-validation.md) for readability measurement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
