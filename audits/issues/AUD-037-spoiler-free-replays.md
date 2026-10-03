# AUD-037 — Offer spoiler-free replay viewing

- **Status:** Open (product proposal)
- **Priority:** P2 — spectator experience
- **Type:** Feature / UX
- **Scope:** combat/app.js replay route, result/title banners and playback state

## Finding and impact

Opening a finished fight shows the verdict and title outcome above the replay
before the viewer watches it. This reduces suspense even when the fight itself
has an interesting comeback.

## Acceptance criteria

- [ ] Offer a spoiler-free viewing mode for completed combat replays, with a clear
  way to reveal the result immediately for builders who are inspecting a loss.
- [ ] In that mode, withhold winner, final HP, title-change outcome and other
  result-revealing content until the replay ends or the viewer opts to reveal it.
- [ ] Ensure hidden spoilers are also absent from accessible labels and announcements.
- [ ] Reaching the final executed beat reveals the same independently checked result
  as the ordinary result view; playback never changes the outcome.
- [ ] Define sensible behavior for seeking, reloads, reduced motion and shared links.
- [ ] Handle forfeits and voids honestly without fabricating combat suspense.
- [ ] Keep the explicit results listing useful for users looking up scores.
- [ ] Test both immediate-result and spoiler-free paths with a comeback and a title fight.

## Related work

Coordinate with [AUD-036](AUD-036-fight-layout-and-readability.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
