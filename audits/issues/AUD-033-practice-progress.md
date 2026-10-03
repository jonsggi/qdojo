# AUD-033 — Give practice a saved record and a clear next challenge

- **Status:** Open (product proposal)
- **Priority:** P2 — repeat play
- **Type:** Feature / UX
- **Scope:** combat/app.js practice flow and local persistence

## Finding and impact

Practice remembers a name and opponent preference, but offers no persistent
per-opponent record or learning progression. After a fight, the main choices
are rematch, new fight and change opponent. Users receive little feedback about
their progress across sessions.

## Acceptance criteria

- [ ] Save per-NPC practice results and a compact record of completed learning
  milestones locally, without requiring a wallet or account.
- [ ] Offer a small recommended sequence that teaches counters, resource management
  and adaptation, with a clear next challenge after each milestone.
- [ ] Keep direct access to opponents for returning and experienced players.
- [ ] Identify the ruleset on saved results; a ruleset change must not silently
  combine incomparable records or invalidate progress without explanation.
- [ ] Show that records are local practice achievements, separate from ranked ratings.
- [ ] Provide a reset control and a usable session when browser storage is unavailable
  or contains malformed/older data.
- [ ] Verify persistence across reloads and confirm results are recorded only once.
- [ ] Observe whether a new player understands what to attempt after their first win.

## Related work

Build on [AUD-032](AUD-032-fight-debrief.md) and the first-session flow in
[AUD-035](AUD-035-first-session-onboarding.md). Sharing is handled separately by
[AUD-034](AUD-034-share-completed-practice-fight.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
