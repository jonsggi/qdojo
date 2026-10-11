# AUD-036 — Put fights and controls ahead of banners and technical detail

- **Status:** Mitigated in 11059267 (replay, arena and title cards lead with the stage; technical detail folded; reading face) and in f147149e, 52c48685, 88be7834 and d4b1f6ee (practice on phones: the arena pinned and fitted to the screen while you plan, steady on every replay frame and showing the state you plan from, and the page opening on the move deck under it and coming back to it when a replay is played out, skipped or left paused, from 360×640 up). Remaining: the new-viewer comparison (beta study, AUD-038/039).
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
- [x] Keep the move deck easy to reach while planning on phones, without duplicate
  controls drifting out of sync or covering essential combat state. *Evidence:* measured
  first on b3e3f71a: at 390×844 and 360×740 every beat, move, POWER, CLEAR and FIGHT was
  below the first screen on arrival (beats from 1,072 and 1,094 px, FIGHT at 1,452 and
  1,474 px) and again after every round, and once scrolled to them both HP bars were off
  the top of the screen. A bottom tray holding the beats would cover the arena's
  POWER/OPENING/GUARD strip and a deck-only tray would split the deck from the beats, so
  on a phone (at most 700 px wide) the practice page pins the arena at the top of the
  screen while a round is open, puts the one planner straight after it (the replay
  controls follow it, on screen and in tab order) and opens on the beats, the deck and
  FIGHT on arrival, after every round and on a rematch. The arena's floor is fitted to
  the screen once per round (at most 170 px, at least 72 px), so the arena keeps one
  height on every frame of a replay and nothing under it moves: the round box hangs into
  the floor and the move strip has a fixed height (none of 920 replay frames at 360 px
  clips its text). It pins from 360×640 up, which covers phone browsers with their
  toolbars showing (375×667, 390×664: the beats and moves are a little tighter there,
  every target still at least 26 px tall); shorter screens and anything wider than
  700 px keep the plain page. Pinned at 390×844, 412×915, 640×960, 360×740, 360×700,
  375×667, 390×664 and 360×640 with six and with eight moves, nothing is off screen,
  covered, under the arena or on an HP bar, both fighters' HP and stamina bars and
  POWER/OPENING/GUARD strips are on screen and uncovered, and nothing scrolls sideways.
  In a first fight the floor shrinks so the coach tip under FIGHT is on the same screen
  from 360×740 up (six or eight moves); on shorter screens it sits just below FIGHT.
  While a round plays back with motion on, the replay controls and the beat headline sit
  right under the arena and hold still, and the page glides back to the deck when the
  round has played to the end (not if the player has scrolled meanwhile) and at once when
  ▶| or ▶ (or END and RIGHT) skips or steps the replay to its end; focus on the replay
  controls goes along to the selected beat. PAUSE, or stepping back, leaves the replay
  on screen, and on a pinned screen the replay controls end with YOUR MOVES ▲ (on the row
  of the beat position, so the controls gain no row): from any frame and any scroll
  position it stops the replay, lands on the deck and focuses the selected beat. While a
  round is planned the pinned arena shows the state it is planned from: landing on the
  deck, or a tap or focus in it, returns a replay left paused or stepped back to its last
  frame (a playing one ends there anyway). With motion off the round is resolved at once
  and the page lands on the deck; the step controls and the headline follow the deck, a
  scroll or TAB away. While round 2 or 3 is planned the arena's round box names that
  round, and the beats are labelled "Your plan for round N".
  The beats are a listbox with one tab stop: the focus moves with the selection (LEFT and
  RIGHT a beat, UP and DOWN a row, HOME and END), a typed move lands on the focused beat,
  the focused beat has the 3 px hazard ring, and focus scrolls clear of the arena (scroll
  padding on the page from the arena's measured height, never inside the beat table). A
  phone turned sideways and back, or a resized window, fits the arena again and lands on
  the deck. Desktop element rectangles at 1280×900 and 1440×900 are identical to b3e3f71a
  (six and eight moves; arrival, mid-round and round 2; re-checked on d4b1f6ee, where
  YOUR MOVES stays hidden on a desktop). The e2e steps `practice-phone`
  (390×844, motion on), `practice-phone-360` and `practice-phone-360-v3` (360×740, motion
  off, coach tip on screen), `practice-phone-v3`, `practice-phone-667`, `practice-phone-664`,
  `practice-phone-700` and `practice-phone-rotate` assert this on arrival, mid-round and
  for round 2 with no scripted scroll, one arena height and beat row on every frame, the
  controls and headline on screen and still during playback, and the listbox keys; they
  fail on b3e3f71a and on 6c57e7a4, where a review found the pin only at 700 px and
  taller, an arena 60–74 px taller on every beat, the narration off screen during
  playback and ROUND 1/3 shown while round 2 was planned (fixed in 88be7834).
  `practice-phone-skip` (390×844, motion on) taps ▶| while round 1 plays, PAUSE while
  round 2 plays (YOUR MOVES on screen, uncovered), ▶ onto the end, YOUR MOVES from a
  stepped-back frame, and a move after stepping back and scrolling up by hand, and checks
  each time the deck on screen and the arena's HP and stamina against the planner's. It
  fails on 4946c190, where a second review found the page left on the replay after ▶|,
  PAUSE or ▶ (FIGHT at 139–184 px under a 0–352 px arena at 390×844, at 109–154 px under
  0–343 px at 360×740), nothing on screen pointing to the deck, and a paused frame's
  HP 84 and STAMINA 60 in the arena while round 2 was planned from 64 and 59 (fixed in
  d4b1f6ee). Screenshots `shots/practice-phone*-{plan,mid,playing,round2}.png` and
  `shots/practice-phone-skip-{last,paused,moves}.png`.
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
