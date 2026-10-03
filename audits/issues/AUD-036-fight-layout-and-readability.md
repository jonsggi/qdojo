# AUD-036 — Put fights and controls ahead of banners and technical detail

- **Status:** Open (design findings from the 2026-09-30 browser review)
- **Priority:** P2 — spectator and mobile usability
- **Type:** UX / accessibility
- **Scope:** combat/app.js, combat/combat.css, combat/shell.css, shared typography

## Finding and impact

On a 1280×900 desktop replay, headings, title banners and a result panel pushed
much of the action below the initial viewport. At 390×844, the practice move
controls were below the first screen. Ticks, protocol detail, ledgers and dense
pixel-font prose compete with the activity the visitor came to see.

These observations motivate a layout/readability improvement, not a claim that
all information must fit in one phone viewport.

## Acceptance criteria

- [ ] Place the fight stage and primary play/step controls before secondary result,
  title-history and protocol panels on replay pages.
- [ ] Keep the move deck easy to reach while planning on phones, without duplicate
  controls drifting out of sync or covering essential combat state.
- [ ] Place ticks, commitment/verification internals and extended accounting in
  accessible detail sections; keep network identity and material status visible.
- [ ] Use a readable body typeface for explanations and dense tables while preserving
  pixel typography, sprites and the established arcade identity in game labels.
- [ ] Verify desktop and phone layouts, including 1280×900 and 390×844, keyboard
  navigation, visible focus, zoom and reduced-motion mode.
- [ ] Retain access to the exact rules, verification results and full ledger data.
- [ ] Compare the revised flow with new viewers: can they find the fight, operate
  playback and locate the explanation of a decisive beat?

## Related work

Coordinate layout changes with [AUD-032](AUD-032-fight-debrief.md) and
[AUD-037](AUD-037-spoiler-free-replays.md). Protocol timing itself remains
[AUD-022](AUD-022-pacing.md); this issue concerns presentation.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
