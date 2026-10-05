# AUD-037 — Offer spoiler-free replay viewing

- **Status:** Fixed in 11059267 (spoiler-free mode), with its e2e steps in the follow-up commit
- **Priority:** P2 — spectator experience
- **Type:** Feature / UX
- **Scope:** combat/app.js replay route, result/title banners and playback state

## Finding and impact

Opening a finished fight shows the verdict and title outcome above the replay
before the viewer watches it. This reduces suspense even when the fight itself
has an interesting comeback.

## Acceptance criteria

- [x] Offer a spoiler-free viewing mode for completed combat replays, with a clear
  way to reveal the result immediately for builders who are inspecting a loss.
  *Evidence:* a SPOILERS: SHOWN/HIDDEN toggle sits in the footer beside MOTION and CRT,
  and in context on each view it affects: the replay's vs line, the results page, the
  title screen's latest results, the arena's result cards and the fighter's fight list.
  The setting is stored in `localStorage` (`qdojo.spoilers`), with every read and write
  in try/catch. A replay shows REVEAL RESULT NOW; each list row has SHOW.
- [x] In that mode, withhold winner, final HP, title-change outcome and other
  result-revealing content until the replay ends or the viewer opts to reveal it.
  *Evidence:* withheld: the result panel, NEW CHAMPION finale and title banner, the
  beat table (it lists every beat and the end), the frame total (it gives away the
  fight's length), check evidence (it names outcome and rating changes), revealed plans
  (rounds played), the corners' current belts, duel/cup series scores, verdict badges
  and "X BEAT Y" lines in lists, and final-HP mini bars on cards. Stage bars show only
  the frame being watched.
- [x] Ensure hidden spoilers are also absent from accessible labels and announcements.
  *Evidence:* withheld content is never rendered, so it is absent from the DOM, `title`
  and `aria-*` attributes too, not just hidden. A DOM sweep (`round3/spectator/sweep.cjs`,
  outerHTML without scripts) on live fights 12102 (title change), 12087 (comeback KO)
  and 12130 (forfeit after two rounds) found no outcome label, outcome badge, NEW
  CHAMPION or BEAT line mid-replay. The `aria-live` beat sentence announces the result
  only on the end frame.
- [x] Reaching the final executed beat reveals the same independently checked result
  as the ordinary result view; playback never changes the outcome. *Evidence:* the end
  frame (by playback, End, or ▶|) reveals the same `resultHtml` the ordinary view
  renders; sweep and e2e check that the revealed text equals `outcomeLabel(replay)`.
  Verification runs identically in both modes.
- [x] Define sensible behavior for seeking, reloads, reduced motion and shared links.
  *Evidence:* seeking to the end reveals; other seeks do not. Revealed fights are
  remembered (`qdojo.spoilers.seen`, the last 300), so a reload or a list does not hide
  a fight already watched. With reduced motion a held replay opens on its first frame,
  not on the result (e2e `spoiler-free-reduced-motion`). Shared links carry no setting:
  each viewer's own applies, and `#fight/<id>/spoilerfree` hides that one replay for
  whoever opens it, without changing their setting.
- [x] Handle forfeits and voids honestly without fabricating combat suspense.
  *Evidence:* the held panel says the fight "may end in combat or on a missed
  deadline", never promising a knockout. A forfeit, double fault or void before any
  round is shown at once, with the note "no round was played, so there is no fight to
  spoil" (e2e `spoiler-free-forfeit`, live 12145). One after played rounds is held and
  reveals TIMEOUT at the end.
- [x] Keep the explicit results listing useful for users looking up scores.
  *Evidence:* held rows keep the fight ID, mode, pairing, title tag and tick. SHOW
  reveals one row, the toggle on the page reveals all, and watched fights show their
  result. The mode is off by default.
- [x] Test both immediate-result and spoiler-free paths with a comeback and a title
  fight. *Evidence:* the immediate path is covered by the existing e2e replay steps
  (default mode). The spoiler-free path is covered by new e2e steps `spoiler-free`,
  `spoiler-free-reduced-motion` and `spoiler-free-forfeit` on the sample (which has no
  title fight), plus the live sweep on title-change fight 12102 and comeback 12087
  (all PASS).

Not covered by this mode (standings, not replays): leaderboard, champions panel,
title lineage, fighter career totals, and duel/cup bracket pages still show
current records.

## Related work

Coordinate with [AUD-036](AUD-036-fight-layout-and-readability.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
