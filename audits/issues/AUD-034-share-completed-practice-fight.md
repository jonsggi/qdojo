# AUD-034 — Make practice sharing preserve the completed fight

- **Status:** Fixed in COMMIT
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

- [x] Provide an actual completed-fight replay artifact or share link containing
  enough inputs to reproduce the fight, including player plans, power slots,
  NPC policy version, seed, fight number and ruleset digest.
- [x] Re-derive the result from those inputs instead of trusting supplied HP or verdicts.
- [x] Open the shared artifact in a clean browser context and reproduce all executed
  beats and the original outcome, including a knockout before round 3.
- [x] A later active-ruleset change cannot silently reinterpret the shared fight.
- [x] Reject malformed, oversized or unsupported artifacts with a useful explanation.
- [x] Retain the existing seeded challenge link if useful, but label it as a new
  challenge rather than the completed replay.
- [x] Cover a complete play → share → fresh-session replay flow in browser tests.

## Resolution (2026-10-03, COMMIT)

The format is in docs/npcs.md §5:

```
#practice/<npc>/<seed>/p1.<fight>.<ruleset digest 16 hex>.<plans per round>.<check 8 hex>
```

It is about 55 characters after the seed.

- **Re-derivation:** the link carries only the player's plans and power slots. The browser re-runs the NPC
  from the seed, fight number and policy id (`jabber-v1` and so on), resolves each round and derives the
  outcome. The check value (SHA-256 of the derived beats and outcome) is only compared. A difference shows a
  red MISMATCH banner above what the plans actually produce.
- **Rulesets:** the digest prefix selects the embedded ruleset. The fight is shown under that ruleset, with a
  note when it differs from the active one, so it is never reinterpreted. An unknown ruleset is refused.
- **Refusals with reasons:** another version, more than 160 characters, a bad NPC or seed, malformed rounds,
  illegal plans, rounds after a KO, and unfinished fights.
- **Address bar:** a finished own fight puts its replay link there, so a reload or copied URL shows the
  completed fight.
- **Labels:** the SHARE panel opens with REPLAY (this exact fight, COPY button) and CHALLENGE, labelled "a new
  fight against the same opponent and seed, not this replay".
- **Evidence:**
  - `practice.test.cjs` round-trips four NPCs on candidate 3, including a KO in round 2, and an older ruleset.
    It also covers tamper detection and each refusal.
  - e2e `practice-share` opens the link in a fresh context and requires the same verdict and identical beat
    rows, then checks MISMATCH and the refusal.
  - Manual runs at 1440 and 390 px on live candidate-3 data: same verdict, `beats identical true`. Screenshots:
    `shots/shared-1440.png`, `shared-390.png` and `mismatch-1440.png`.

## Related work

Use the independent replay machinery already present.
[AUD-041](AUD-041-builder-journey-acceptance.md) should exercise this user-visible
promise as part of the practice path.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
