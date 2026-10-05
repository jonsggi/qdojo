# AUD-032 — Turn fight results into an actionable debrief

- **Status:** Fixed in COMMIT (implementation); the new-player criterion stays open under AUD-038
- **Priority:** P1 — learning and repeat play
- **Type:** UX / feature
- **Scope:** combat/logic.js, combat/app.js practice and replay results, combat/training.py explanations

## Finding and impact

The engine and UI already expose beat explanations and hindsight alternatives.
Users still have to inspect traces to decide which moments mattered and what to
change. A result should help a new player move from losing to trying a better plan.

The review proposes a short debrief that surfaces existing evidence; a new
generative explanation service is not required.

## Acceptance criteria

- [x] Show a concise post-fight summary with a small number of decisive or costly
  exchanges and links that seek to the relevant replay beats.
- [x] Explain observed causes in plain language, including exhausted attacks,
  punished recovery, wasted power, and candidate-3 interactions when relevant.
- [x] Suggest a specific next experiment or practice opponent from those observations.
- [x] Label alternatives as hindsight against the recorded opposing move; never
  promise that a different plan would force the same opponent response.
- [x] Separate combat lessons from timeouts/forfeits and never invent decisive
  beats for an unfinished or unplayed round.
- [x] Preserve access to full traces and identical information with motion disabled.
- [ ] (recorded examples done; new players open) Validate with recorded examples and new players: can they identify a relevant
  mistake and name a change they intend to try?

## Resolution (2026-10-03, COMMIT)

`apps/web/combat/practice.js` `debrief()` builds the debrief from engine traces only. `app.js` renders it as the
DEBRIEF panel under every finished practice fight, and as a folded panel labelled "SHOWS THE RESULT"
under every arena replay.

- **Key beats:** at most three largest HP swings plus the finishing blow, in fight order. Each has an `R# B#`
  button that seeks the replay player to that frame (e2e `practice-debrief` checks it).
- **Causes:** counted per side from trace reasons. They cover EXHAUSTED beats and the HP they cost, punished
  RECOVERs, POWER_WASTED, blocked or ducked attacks, interrupted throws, openings that expired, FEINT baits and
  GUARD_BROKEN follow-ups, LAST STAND bonuses, and guard strain.
- **Habits:** action counts over executed beats only, plus beat positions that repeated in every round reached.
- **Hindsight:** a beam search (width 48) over the player's plan for one played round, against the NPC plan
  recorded for that round. The engine re-runs the result (`resolveRound`) to get the stated numbers.
  Practice NPC plans are sealed before the human picks, so this is exact for that round. The text says
  "Hindsight ... exact for that round only ... later rounds would have changed" and never promises the
  opponent's response.
- **Tip:** one per fight, from the costliest observed habit; a counter tip is scored by the engine on a fresh
  beat. In arena replays, a practice-opponent suggestion follows from the loser's main cause.
- **Unplayed beats:** forfeit and timeout fights carry the outcome label and say that unplayed rounds hold no
  lesson. A fight with zero played beats gets no key beats and no advice.
- **Motion:** static text, so motion settings change nothing. The beat table and recap stay unchanged.
- **Evidence:**
  - `apps/web/tests/practice.test.cjs` checks swings against traces and re-runs the hindsight plan through
    the engine.
  - It also runs the debrief over every sample replay: no key beat comes from a non-executed beat, and
    forfeits are flagged.
  - Screenshots: `scratchpad/round3/practice-ux/shots/result-1440.png` and `result-390.png`.
- **Remaining:** whether new players can name a mistake and a change is a human-study question, handed to
  AUD-038.

## Related work

Pair with [AUD-033](AUD-033-practice-progress.md) for follow-through and
[AUD-038](AUD-038-human-strategy-validation.md) for readability measurement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
