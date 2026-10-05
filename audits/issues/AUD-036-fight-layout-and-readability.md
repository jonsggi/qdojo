# AUD-036 — Put fights and controls ahead of banners and technical detail

- **Status:** Mitigated in 70bc1990 (replay, arena and title cards lead with the stage; technical detail folded; reading face). Remaining: the phone move deck in practice (practice-ux track, AUD-032/035) and the new-viewer comparison (beta study, AUD-038/039).
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

- [x] Place the fight stage and primary play/step controls before secondary result,
  title-history and protocol panels on replay pages. *Evidence:* `#fight/<id>` is now
  title, one vs line (fighters, TITLE FIGHT tag, LIVE badge, verification level, series
  link, spoiler toggle), then the stage and controls; the result panel, title banner,
  live-deadline banner, verification and plans follow. Before/after at 1440, 1024, 390
  and 360 px (`round3/spectator/before/`, `after/`): before, the stage started below
  the first screen on both phone widths; after, stage and PLAY/step controls are on
  the first screen at every width. Arena cards put the stage before phase and acted rows.
- [ ] Keep the move deck easy to reach while planning on phones, without duplicate
  controls drifting out of sync or covering essential combat state. *Not changed here:*
  the practice planner belongs to the practice-ux track (AUD-032/035); left to that track
  to avoid conflicting edits in the same view.
- [x] Place ticks, commitment/verification internals and extended accounting in
  accessible detail sections; keep network identity and material status visible.
  *Evidence:* VERIFICATION is a `<details>` panel (opens by itself when the level is
  FAILED); REVEALED PLANS folds per round. The verification level stays visible in the
  vs line, the network badge in the HUD, NETWORK/ARENA LIMITS on the arena, and a live
  fight keeps its LIVE badge and deadline banner.
- [x] Use a readable body typeface for explanations and dense tables while preserving
  pixel typography, sprites and the established arcade identity in game labels.
  *Evidence:* `combat/spectator.css` adds `--font-read` (system sans) for the beat
  sentence, captions, beat-table explanations, check evidence, result/live/verification
  prose and arena notes. Badges, buttons, stage numbers, titles and sprites keep
  Press Start 2P.
- [x] Verify desktop and phone layouts, including 1280×900 and 390×844, keyboard
  navigation, visible focus, zoom and reduced-motion mode. *Evidence:* screenshots at
  1440×900, 1024×900, 390×844 and 360×844 (reflow at 360 CSS px matches 400 % zoom of a
  1440 px window); web e2e 37/37 including keyboard steps (focus the beat table, End,
  Home and arrows), reduced-motion parity, and no sideways scroll at 375 px. Focus rings
  come from the existing `:focus-visible` rule, which also covers the new toggles and
  summaries.
- [x] Retain access to the exact rules, verification results and full ledger data.
  *Evidence:* nothing removed: every check, its evidence and details, plans, salts,
  commitments and digests are one click away; e2e `replay`/`tampered` still read every
  check status.
- [ ] Compare the revised flow with new viewers: can they find the fight, operate
  playback and locate the explanation of a decisive beat? *Needs owner:* part of the
  outside-builder study (AUD-038/039); no viewer sessions were run here.

## Related work

Coordinate layout changes with [AUD-032](AUD-032-fight-debrief.md) and
[AUD-037](AUD-037-spoiler-free-replays.md). Protocol timing itself remains
[AUD-022](AUD-022-pacing.md); this issue concerns presentation.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
