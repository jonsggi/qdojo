# AUD-035 — Make the first session lead clearly to playing and building

- **Status:** Fixed in 1fbced09 for the title and practice entry; the BUILD A BOT content, outside-entry status and cohort trial stay with builder-journey (AUD-027/041) and AUD-039
- **Priority:** P1 — activation
- **Type:** UX / onboarding
- **Scope:** title screen, practice introduction, BUILD A BOT page and builder guide

## Finding and impact

PRESS START on the title screen leads to the arena, where the visitor watches.
The builder page then presents an extensive planner contract. The site does
not provide one short guided journey from curiosity to a first personal result
and a running bot.

The review recommends making independent bot builders the primary audience
for the next milestone, with manual practice as their introduction.

## Acceptance criteria

- [x] Give visitors explicit play and watch actions; labels match their destinations.
- [x] Offer a short optional path: name a fighter, complete a guided first practice
  fight, inspect one useful lesson, then download/run the starter planner.
- [x] Teach the initial plan through interaction and contextual guidance without
  requiring the full damage matrix or protocol specification first.
- [x] Make advanced reference material available alongside the guided path.
- [ ] (BUILD A BOT page: builder-journey / AUD-027) Show outside-entry availability and the correct next action; a closed arena
  must not be presented as a completed registration step.
- [x] Preserve direct navigation and a skip path for returning users.
- [ ] (needs a cohort, AUD-039) Try the published path with independent builders and record time to first
  completed arena fight, confusion and assistance required.

## Resolution (2026-10-03, 1fbced09)

- **Title:** PRESS START (which went to the arena) is replaced by PLAY ▶ (`#practice`) and WATCH (`#arena`),
  with a line saying what each does. Below them is an optional NEW HERE? FOUR STEPS path: name a fighter,
  first fight vs JABBER, read your debrief, build your bot (`#join`). Steps tick from the local record. A
  returning player sees WELCOME BACK and the next challenge instead.
- **Practice entry:** before the first fight, a four-step FIRST FIGHT coach box appears and JABBER is
  preselected as ladder step 1. Round one shows a COACH line from the NPC's disclosed behaviour ("A DUCK slips
  under a JAB"); the matrix is not required first.
- **After the fight:** the debrief (AUD-032) and a BUILD YOUR OWN BOT ▶ button.
- **Unchanged:** the menu, RULES and the full scouting report stay available, and nothing is gated.
- **Not touched:** the BUILD A BOT page belongs to the builder-journey track; the step only links to it and
  claims no entry. Its outside-entry availability statement is that track's (AUD-027 site part).
- **Evidence:**
  - e2e `title` checks PLAY goes to `#practice`, WATCH to `#arena`, and the path is shown.
  - Screenshots: `shots/title2-1440.png`, `title-390.png` and `select2-390.png`.

## Related work

[AUD-029](AUD-029-starter-planner-new-moves.md) and
[AUD-030](AUD-030-onboarding-ruleset-consistency.md) make the recommended commands
reliable. Entry is tracked by [AUD-027](AUD-027-outside-builder-entry.md);
the proposed ten-minute target and cohort are owned by
[AUD-039](AUD-039-builder-beta-and-commercial-evidence.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
