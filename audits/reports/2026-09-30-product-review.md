# QDOJO product review: from playable demo to an independent builder beta

> **Reviewed:** 2026-09-30. \
> **Recorded as issues:** 2026-10-03. \
> **Scope:** product experience, onboarding, selected implementation paths and
> validation evidence; not a complete regression or security audit.

## Assessment

QDOJO is a distinctive playable demo with the foundations for a bot-building
competition. The scrapyard robots, stages, lore and title belts give it a
recognizable identity. Equal combat stats, hidden plans, deterministic resolution
and independently checked replays support a credible competitive promise.

The engineering and visual identity are ahead of onboarding and evidence of
repeat participation. The proposed next milestone is a small free cohort of
independent builders who build, compete, study and revise their bots.
That is a product recommendation, not evidence that the beta has happened or
that a paid business has been validated.

## Evidence and limits

The September review inspected the live site on desktop and mobile, played a
practice bout, opened replays, read recent changes and the implementation, and
examined the candidate-3 validation report.

- The live manifest selected candidate 3. The status endpoint reported outside
  entry disabled, and all 20 fighter metadata records were marked house-run.
- A sample of the latest 200 finished fights contained 196 combat results and
  four forfeits. This was an operational snapshot, not independent participation
  or retention evidence.
- The supplied planner crashed when LAST_STAND or FEINT was the most frequent
  observed opponent move. Both failures were reproduced again on 2026-10-03.
- The CLI defaulted to candidate 1 while the agent briefing recommended candidate 2
  as the live rules. These source inconsistencies remained at 2eb5ef8b.
- After a completed practice fight, opening its share link started a new fight.
  The opponent-and-seed-only link construction remained at 2eb5ef8b.
- At 1280×900, replay banners and result panels pushed much of the action below
  the initial viewport. At 390×844, practice move controls required scrolling.
- At 2eb5ef8b, combat/app.js contained 3,101 lines and 251,005 bytes.

The live observations above are dated 2026-09-30. They were not remeasured against
the deployed service when these issues were written. Relevant source paths were
rechecked at 2eb5ef8b on 2026-10-03. Subsequent contract work, including the
candidate-3 Qubic port and asset binding, is recorded in
[the contract README](../../contracts/qubic/README.md); the review must not be
read as claiming that this implementation work is still absent.

The September checks passed 34/34 browser steps, 69 focused Python tests, and
the active-document link/rules-matrix check. Longer full-suite runs were stopped
before completion. These results are historical checks, not a current release
certification. In particular, they did not catch the complete onboarding and
practice-sharing failures above.

## Issue coverage

| Review concern | Issue |
|---|---|
| Outside users cannot complete the participation loop | [AUD-027 — outside-builder entry](../issues/AUD-027-outside-builder-entry.md), extended with beta enablement criteria |
| Starter crashes on new moves and budgets with old constants | [AUD-029 — starter compatibility](../issues/AUD-029-starter-planner-new-moves.md) |
| Website, docs, commands and active game disagree | [AUD-030 — ruleset consistency](../issues/AUD-030-onboarding-ruleset-consistency.md) |
| Custom-planner evaluation requires an extra script | [AUD-031 — custom benchmarks](../issues/AUD-031-custom-planner-benchmark.md) |
| Players need help understanding a loss and trying a change | [AUD-032 — fight debrief](../issues/AUD-032-fight-debrief.md) |
| Practice lacks persistent progress and a next challenge | [AUD-033 — practice progress](../issues/AUD-033-practice-progress.md) |
| Shared practice links do not replay the completed fight | [AUD-034 — completed-fight sharing](../issues/AUD-034-share-completed-practice-fight.md) |
| PRESS START and the builder flow do not guide first participation | [AUD-035 — first-session onboarding](../issues/AUD-035-first-session-onboarding.md) |
| Banners, technical detail and typography compete with the fight | [AUD-036 — layout and readability](../issues/AUD-036-fight-layout-and-readability.md) |
| Results spoil replays before viewers watch them | [AUD-037 — spoiler-free replays](../issues/AUD-037-spoiler-free-replays.md) |
| Simulated balance gates do not establish human learning or a lasting metagame | [AUD-038 — human strategy validation](../issues/AUD-038-human-strategy-validation.md), extending AUD-021 |
| Commercial development has little independent demand evidence | [AUD-039 — builder beta and commercial evidence](../issues/AUD-039-builder-beta-and-commercial-evidence.md) |
| The frontend controller has too many responsibilities | [AUD-040 — frontend modules](../issues/AUD-040-frontend-modules.md) |
| Existing checks miss the published journey under current rules | [AUD-041 — builder journey acceptance](../issues/AUD-041-builder-journey-acceptance.md) |

Existing real-cost, player-economics and licensing work remains in
[AUD-018](../issues/AUD-018-house-economics.md),
[AUD-019](../issues/AUD-019-player-ev-and-event-farming.md) and
[AUD-028](../issues/AUD-028-licence.md). These are dependencies and related work,
not duplicate new findings.

## Suggested sequence

1. Fix the starter and version agreement (029–030), add custom evaluation (031),
   and protect the published journey with acceptance coverage (041).
2. Complete the outside-entry milestone (027) and first-session guidance (035);
   fix sharing (034) and surface actionable debriefs (032).
3. Run the ten-builder cohort and human strategy/readability study (039, 038).
   Record first-fight completion, time and assistance, second submissions,
   repeat participation after one week, and explanations of improvement.
4. Use those observations to refine practice progression (033), layout (036)
   and spectator presentation (037). Split the frontend incrementally (040)
   as these journeys are changed.

Ten participants and a first arena fight within ten minutes are proposed
research targets. Report failures and drop-offs as well as successful attempts.
Freeze the ruleset for the study, recording any necessary corrections, so
strategy changes and learning remain interpretable.

## Preserve

Retain the arcade identity, accessible free practice, equal combat stats,
versioned deterministic rules, independent replay checks and the separation
between planners, authority and presentation. Commercial priorities should
follow measured engagement; simulated turnover alone cannot establish
willingness to pay.
