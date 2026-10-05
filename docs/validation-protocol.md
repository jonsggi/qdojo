# Human validation protocol

> **Purpose:** how the builder beta measures what simulation cannot: whether people can read replays, build and revise bots, adapt to a changing opponent, and want to come back. Hypotheses, tasks, measures and pass thresholds, fixed before recruiting. \
> **Audience:** the study team, reviewers of the next rules decision, and anyone quoting beta results. \
> **Status:** proposal (written 2026-10-03 for AUD-038 and AUD-039). It defines measurements and claims none; no session has been run. \
> **Last reviewed:** 2026-10-03

The gates come from [model.md](model.md) §2–3; what simulation has measured
so far is in [validation-status.md](validation-status.md). The beta itself
(cohort, entry, limits, timeline) is [beta.md](beta.md). Candidate 3's 11/11
strategic gates are measured properties of a declared policy pool; they are
not evidence of human understanding, enjoyment or a lasting metagame, and no
result of this protocol is to be reported as if they were.

## Contents

- [1. Frozen conditions](#1-frozen-conditions)
- [2. Hypotheses](#2-hypotheses)
- [3. Measures and thresholds](#3-measures-and-thresholds)
- [4. Tasks and data](#4-tasks-and-data)
- [5. Instruments](#5-instruments)
- [6. Analysis and reporting](#6-analysis-and-reporting)
- [7. Privacy](#7-privacy)

## 1. Frozen conditions

Before the first session the study team records, in the study log:

- **Ruleset:** candidate 3, digest `cf19b7cf…` (the arena's `devnet.json`).
- **House policies:** the lineup file's SHA-256 and the live checkout's
  commit ([beta.md](beta.md) §5 step 1). Planner and NPC versions follow from
  the commit.
- **Tooling:** the released `qdojo` version the invitations point to.
- **One scheduled change:** a single house sparring bot switches style at a
  tick chosen in advance and recorded in the log but not announced (H7). The
  operator changes that bot's lineup entry (for example `kicker-v1` to
  `jabber-v1`) and restarts the arena; the restart tick is the switch tick.

No moves or rules are added during the beta. A correction that cannot wait
(a crash, a rules bug) is applied, its tick recorded, and every later row of
the cohort log carries `cohort_phase = after-correction`; results are
reported separately for each phase. Old replays stay verifiable: a rules
correction means a new arena, and the old one's journal and export are kept.

## 2. Hypotheses

| | Hypothesis | Gate it serves |
|---|---|---|
| H1 | Replays are readable: viewers can name what caused a decisive exchange from the replay UI alone, including LAST STAND, FEINT and guard breaks, resource failures, simultaneous trades and forfeits, with reduced motion as well | model.md §3 (8 of 10) |
| H2 | Independent builders can implement a bot from the public docs and tooling and get it into an arena fight; some take approaches other than the starter | model.md §3 (independent implementers); AUD-027 |
| H3 | First arena fight within ten minutes for most people who start | AUD-039 onboarding target |
| H4 | Practice teaches a useful improvement in a short session, which the builder can explain and demonstrate | model.md §3 (free NPC practice) |
| H5 | Builders revise: they submit a second version after studying fights | AUD-039 (build → compete → study → revise) |
| H6 | Builders come back a week later of their own accord | AUD-039 (repeat participation) |
| H7 | Bots adapt to an opponent that changes style; stale assumptions have a measurable cost | model.md §2 (adaptation time, cost of stale assumptions) |
| H8 | People perceive counterplay and want to watch or play again | AUD-038 (session feedback) |

## 3. Measures and thresholds

Thresholds were chosen before any data exists and are not to be lowered
after seeing it (model.md §2). With ten participants every rate is reported
with its count and a 95% Wilson interval; a pass is a reason to continue,
not a proof.

| | Measure | Pass |
|---|---|---|
| H1 | Per reviewer: decisive exchanges whose cause they identify (first-named cause is one the engine's beat detail supports), out of 10. Separately: the reduced-motion items, and each required category | **Every** reviewer ≥ 8/10 (model.md §3). Reported per category; any required category below 60% pooled is a finding even if the gate passes |
| H2 | Participants who started and reached a completed arena fight (not a forfeit), and the approach of each: `starter`, `modified_starter`, `independent` (judged from a short code walk-through, T4) | ≥ 7 of 10; at least 2 not `starter` |
| H3 | Minutes from start (T1) to first completed arena fight, everyone who started in the denominator, dropouts counted as over | ≥ 50% within 10 minutes without `hands_on` help |
| H4 | Participants who can explain an improvement and show it: a named NPC or house bot against which an evaluation or arena record improved | ≥ 6 of 10 |
| H5 | Second submission within the beta (self-report, cross-checked against bot runs in `/api/v1/community`) | ≥ 5 of 10 |
| H6 | Returned in week 2 by their own choice (self-report and session log; a bot left running does not count) | Reported only |
| H7 | Per builder fighter with ≥ 5 fights on each side of the switch against the switching bot: score before, first five after (stale cost), fights until the five-fight mean is back within 0.1 of before (adaptation time) | Reported only (model.md §2 asks for a report) |
| H8 | 1–5 survey: clarity, perceived counterplay, desire to replay; plus open answers | Reported; a median below 3 on clarity or counterplay is a finding |

Every participant counts in the denominator of every rate from the moment
they start, and drop-off reasons are reported with the rates.

## 4. Tasks and data

| Task | When | What is recorded |
|---|---|---|
| T1 Start | Onboarding session (observed, screen shared or think-aloud) | `started_at` when they open the builder page |
| T2 Practice | Same session | Whether they used practice first; what they changed |
| T3 First arena fight | Same session | `first_fight_at` when their first fight finishes; `assistance`: `none`, `docs` (pointed to a doc), `hint`, `hands_on`; or `dropped_at_step` and `drop_reason` |
| T4 Code walk-through | End of week 1, 10 minutes | `approach` |
| T5 Replay review | Week 1 (5 reviewers from the cohort; up to 2 internal reviewers logged separately) | Each reviewer gets 10 sampled exchanges (§5), 2 of them with reduced motion, and picks causes |
| T6 Closing interview | Week 3 | `second_submission`, `returned_week_2`, `explained_improvement` (y / partial / n, with the demonstration), survey 1–5, open feedback |

Columns of the cohort log, one row per participant:
[fixtures/beta-cohort-template.csv](fixtures/beta-cohort-template.csv)
(`participant, cohort_phase, house_or_test, started_at, first_fight_at,
assistance, dropped_at_step, drop_reason, approach, second_submission,
returned_week_2, explained_improvement, clarity, counterplay, replay_desire`).
House and test identities are logged with `house_or_test = y` and excluded.

## 5. Instruments

All in `packages/qdojo/src/qdojo/study.py`, run by `scripts/beta-study.py`,
tested in `packages/qdojo/tests/test_study.py`:

- **Readability sheets** (`sample`): from the export's finished replays, the
  decisive exchange of each fight: the round of a forfeit, the knockout beat,
  or the beat with the largest HP swing towards the winner of a decision
  (draws are skipped). Each exchange gets cause categories from the engine's
  own beat detail (reason codes, intended against effective action, HP lost
  on each side). One set of 10 per reviewer covers every required category
  the pool contains (LAST STAND, FEINT/guard break, resource failure,
  simultaneous trade, forfeit) and marks 2 items for reduced motion. It writes
  `sheets.md` and `sheets.json` for reviewers and `key.json` for the team, and
  prints which required categories the pool lacked. On the live export of
  2026-10-03 the pool held 198 exchanges and every required category
  (forfeits: 7).
- **Scoring** (`score`): answers as CSV `reviewer,item,causes`; prints the
  identified rate with its interval, the sorted reviewer scores, per-category
  and reduced-motion results, and the H1 gate.
- **Cohort report** (`cohort`): the H2–H6 and H8 aggregates per phase.
- **Adaptation** (`adaptation`): H7 from the read model's per-fighter results
  against the switching bot.
- **Arena participation** (`GET /api/v1/community`, [beta.md](beta.md) §7):
  outside fighters, active builder keys, fights by pairing, bot runs.

## 6. Analysis and reporting

At the end of the beta the study team publishes, in
[validation-status.md](validation-status.md), a section "Human validation:
beta cohort" with: participant counts per phase, every measure in §3 with
counts and intervals, each hypothesis as pass / fail / reported, the drop-off
reasons, the failed readability items by category, and what was changed in
response. Failed cases are described, never omitted. The next rules decision
(AUD-038's last criterion) is made from that section and recorded in
[product decisions](product-decisions.md); if a new candidate follows, the
current one's artifacts and replays are kept and versioned.

## 7. Privacy

Study data holds pseudonyms only (P01, R01). The mapping to contacts stays
with the owner, outside the repository, and is deleted after the beta. The
cohort log and answer files are never committed or served. Every instrument
prints aggregates (counts, rates, distributions) and no row. The arena-side
measurements read only public chain and arena data; the site has no
analytics for this ([beta.md](beta.md) §8).
