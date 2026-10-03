# AUD-034 — Make practice sharing preserve the completed fight

- **Status:** Open; reproduced in the browser 2026-09-30, code rechecked 2026-10-03
- **Priority:** P1 — public correctness and sharing
- **Type:** Bug
- **Scope:** combat/app.js renderPracticeFight/viewPractice, practice replay format and verifier

## Finding and impact

The SHARE / REPLAY THIS FIGHT link contains only the NPC id and seed:
`#practice/<npc>/<seed>`. It omits the player's submitted plans and ruleset.
Opening it starts round 1 with full resources instead of replaying the fight.
Friends cannot see the clever win or mistake the player intended to share.

## Reproduction

1. Open practice and finish a bout against JABBER.
2. Copy the link under SHARE / REPLAY THIS FIGHT.
3. Open it in a fresh tab/session, or reload the current page.
4. Observe ROUND 1 OF 3 with an empty move deck rather than the completed result.

The link is built in combat/app.js around line 2081. The route recreates
practice state from the opponent and seed.

## Acceptance criteria

- [ ] Provide an actual completed-fight replay artifact or share link containing
  enough inputs to reproduce the fight, including player plans, power slots,
  NPC policy version, seed, fight number and ruleset digest.
- [ ] Re-derive the result from those inputs instead of trusting supplied HP or verdicts.
- [ ] Open the shared artifact in a clean browser context and reproduce all executed
  beats and the original outcome, including a knockout before round 3.
- [ ] A later active-ruleset change cannot silently reinterpret the shared fight.
- [ ] Reject malformed, oversized or unsupported artifacts with a useful explanation.
- [ ] Retain the existing seeded challenge link if useful, but label it as a new
  challenge rather than the completed replay.
- [ ] Cover a complete play → share → fresh-session replay flow in browser tests.

## Related work

Use the independent replay machinery already present.
[AUD-041](AUD-041-builder-journey-acceptance.md) should exercise this user-visible
promise as part of the practice path.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
