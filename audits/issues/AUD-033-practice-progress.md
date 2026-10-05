# AUD-033 — Give practice a saved record and a clear next challenge

- **Status:** Fixed in 1fbced09; the first-win comprehension observation stays open under AUD-038
- **Priority:** P2 — repeat play
- **Type:** Feature / UX
- **Scope:** combat/app.js practice flow and local persistence

## Finding and impact

Practice remembers a name and opponent preference, but offers no persistent
per-opponent record or learning progression. After a fight, the main choices
are rematch, new fight and change opponent. Users receive little feedback about
their progress across sessions.

## Acceptance criteria

- [x] Save per-NPC practice results and a compact record of completed learning
  milestones locally, without requiring a wallet or account.
- [x] Offer a small recommended sequence that teaches counters, resource management
  and adaptation, with a clear next challenge after each milestone.
- [x] Keep direct access to opponents for returning and experienced players.
- [x] Identify the ruleset on saved results; a ruleset change must not silently
  combine incomparable records or invalidate progress without explanation.
- [x] Show that records are local practice achievements, separate from ranked ratings.
- [x] Provide a reset control and a usable session when browser storage is unavailable
  or contains malformed/older data.
- [x] Verify persistence across reloads and confirm results are recorded only once.
- [ ] (needs a study, AUD-038) Observe whether a new player understands what to attempt after their first win.

## Resolution (2026-10-03, 1fbced09)

- **Storage:** `localStorage` key `qdojo.practice.v1` holds W/L/D and the best result per NPC under each
  ruleset version, plus the first-session steps. Every access is in try/catch.
- **Ladder:** the select screen shows YOUR PRACTICE RECORD: a six-step ladder (JABBER read a pattern, KICKER
  punish the recovery, TURTLE crack a guard, RANDOM spend wisely, MIXED out-budget, SCOUT adapt). Each step
  shows its record, a NEXT tag and a NEXT CHALLENGE button. Cards show their record.
- **Next challenge:** the result screen shows the record line, NEW BEST, a MILESTONE when a ladder step is
  first won, and a NEXT CHALLENGE button. All six opponents stay directly selectable; nothing is locked.
- **Rulesets:** records under other rulesets are listed as "kept, not combined". The panel says the record is
  local and separate from ranked ratings, with no QU.
- **Reset and bad data:** RESET RECORD asks for confirmation. Malformed or older data is ignored with a notice.
  Blocked storage gives a notice and an in-memory record, and the site keeps working.
- **Counted once:** each fight is keyed by its share identity, so a reload or reopening its link does not
  count it again.
- **Evidence:**
  - `practice.test.cjs`: record-once, ladder order, rulesets kept apart, round trip, and bad JSON or
    versions.
  - e2e `practice-debrief`: recorded once, and a reload adds no record line.
  - e2e `practice-no-storage`: a full round works with storage throwing.
  - Screenshots: `shots/select-after-1440.png` and `select-390.png`.

## Related work

Build on [AUD-032](AUD-032-fight-debrief.md) and the first-session flow in
[AUD-035](AUD-035-first-session-onboarding.md). Sharing is handled separately by
[AUD-034](AUD-034-share-completed-practice-fight.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
