# Combat validation and economics

> **Purpose:** the acceptance gates combat must pass: correctness, exploits, optimisation reward, fight shape, readability, timing, money and farming. \
> **Audience:** reviewers deciding whether the ruleset is fit to launch. \
> **Status:** normative (the gates). It defines measurements and claims none. Results so far are in [validation-status.md](validation-status.md): mechanical correctness and the 11 strategic gates measured so far pass on held-out seeds. Not measured: adaptation time against a style-switching opponent, §3 readability, §4 timing and contract cost, and economics with real costs. \
> **Last reviewed:** 2026-09-26 (§4 demo timing and §8 balance measurements added; the gates are unchanged)

Historic riddle experiments are [archived](archive/riddle-v0/docs/model.md) and are not combat evidence.

## Contents

- [1. What success must mean](#1-what-success-must-mean)
- [2. Required experiments](#2-required-experiments)
- [3. Human readability and bot development](#3-human-readability-and-bot-development)
- [4. Timing and compute](#4-timing-and-compute)
- [5. Money model](#5-money-model)
- [6. Farming and adversarial participation](#6-farming-and-adversarial-participation)
- [7. Acceptance report](#7-acceptance-report)
- [8. Balance measurements: candidate 1 and candidate 2](#8-balance-measurements-candidate-1-and-candidate-2)

## 1. What success must mean

The design must reward better planning, resource management and opponent
adaptation while preserving uncertainty from hidden decisions. Adding moves
or a large sequence space is not itself evidence. The simulator is public;
the owner optimizes a policy, not an expensive secret evaluator.

Use win=1, draw=0.5, loss=0 for performance score. Report draw, KO, forfeit,
HP margin, stamina/exhaustion, power usage, opening conversion and compute cost
separately. A forfeit win is not evidence of strategic superiority.

Freeze ruleset, policy versions, training/evaluation budgets and seeds before
evaluating. Always swap fighter slots with paired seeds. Use held-out policies
as well as fresh seeds. Do not tune on the published acceptance set and keep
calling it held-out.

## 2. Required experiments

### Mechanical correctness (hard gate)

- All 49 effective-action pairings, both directions, all boundary costs.
- HP=1, simultaneous KO, bonuses on blocked attacks, exhausted power,
  guard-strain underflow, capped regeneration, third-round tie.
- At least 100,000 generated reachable paired states/plans with slot symmetry,
  determinism, integer ranges and trace conservation properties.
- Independent Python and C++ execution, plus browser replay, on at least
  10,000 frozen full-fight fixtures. No mismatches.
- Replay every hand vector in [combat.md](combat.md).
- Protocol/financial/matchmaking cases from the owning documents.
- Reject impossible state and malformed plan instead of repairing silently.

### Baselines and obvious exploits (hard gate)

Run all fixed single-action spam policies, random-v1 and the NPC roster.
Include two-action cycles, repeat-the-last-winning-plan, always-save/spend-power,
recovery at fixed slots, stall-for-draw and deliberate exhaustion.
Enumerate all six-action OPENING plans against representative policies where
feasible; do not interpret one-round search as solving the entire game.

An alleged universal policy must be challenged by best-response search,
adversarial training and adaptive opponents. Every simple spam/cycle strategy
must have at least one practical counter achieving mean score >=0.60 with a
paired-bootstrap 95% lower bound >0.55 on at least 2,000 held-out fights.
Failure is a release blocker, not a reason to omit that baseline.

### Optimization reward (hard gate)

Compare four declared compute budgets: random, heuristic, bounded search,
and trained/adaptive policy. At least one <=1500-ms planner must score >=0.65
against random-v1 and >=0.60 against the held-out fixed-style pool, with
95% lower bounds >0.60 and >0.55 respectively over >=2,000 fights/pool.
Publish per-opponent results, not only a pooled headline.

Compare the improved planner to its own ablated version with opening/resource
state disabled. Show a >=0.05 score improvement against the same held-out pool,
paired 95% lower bound >0. This checks whether the intended planning matters.
If optimization merely memorizes one opponent seed, it fails.

### Opponent learning and surprise (hard gate)

Use at least three exploitable opponent families with withheld parameter
variants, plus memoryless randomized and adaptive opponents.

- Against predictable families, history-aware play should improve mean score
  by >=0.05 over its history-blind ablation (paired 95% lower bound >0).
- Against memoryless random-v1, do not require a history advantage; there is
  no stable hidden pattern to learn. Measure overfitting and calibration.
- Against an opponent that changes its style between fights, report adaptation
  time and the cost of stale assumptions.
- Feed the same round-start state to policies with different own historical
  beliefs. Confirm at least two competitive plans occur, rather than claiming
  hidden plans are surprising when every strong policy selects the same one.
- Show counterplay to a successful exploiter using a changed/mixed policy.
  No single published deterministic six-action script should win universally.

No finite experiment proves an unsolved game. If practical search finds a
near-universal simple policy, redesign before freezing the rules. A strong
mixed equilibrium is possible; the question is whether learning/engineering
still produces a worthwhile game around it.

### Diversity and fight shape (initial acceptance bands)

On the declared competent-policy pool, excluding intentionally passive NPCs:

| Measure | Candidate acceptance band |
|---|---|
| Combat draws | <=15% |
| Fights reaching round 2 (third round, zero-indexed) | >=40% |
| Round-0 knockouts | <=20% |
| Wins by a fighter trailing in HP after round 0 | 10..40% of such fights |
| Opening converted into positive bonus damage | Report by policy/opponent |
| Exhausted beats for competent policies | <10%, excluding intentional stress cases |
| Practical strategy families | >=3 distinct policies with score >=0.45 against the pool |

Report uncertainty and sample counts. These bands express desired pacing and
comeback frequency; they are not permission to add hidden catch-up damage.
If they cannot be met together, record the tradeoff and revise the candidate
rules in a new version. Do not silently lower gates to match one run.

A small executable reference and arithmetic checks in
[reference/combat_v1.py](reference/combat_v1.py) are a specification aid.
Its smoke tournament, if run, is NOT the above acceptance campaign.

## 3. Human readability and bot development

Before external paid onboarding, internal reviewers should identify what caused
at least 8 of 10 sampled decisive exchanges using only the replay UI.
Verify simultaneous trades, resource failures, unused suffixes and forfeit
labels. Reduced motion must retain the same information.

Have independent implementers build a simple bot using only the public docs/SDK.
Record ambiguities and fix the specification. Model size is not a reason to
leave ordering, flags or terminal outcomes implicit.

Free NPC practice should teach a useful improvement within a short session:
e.g. counter jabber-v1, then discover that the same plan loses to kicker-v1.
This is a usability target to evaluate, not a promised retention result.

## 4. Timing and compute

Measure separately: queue wait, match confirmation, planning, commit inclusion,
reveal inclusion, resolution, export freshness, visible playback, withdrawal.
Median/P95/P99 and faults under realistic load are required.

Target matched-fight wall time: median <=60 seconds, P95 <=90 seconds for
healthy clients. Candidate 24/12 tick windows are not converted to seconds
using a historic assumed tick duration. Measure current network distribution.
A six-beat replay should fit inside the next commit window at normal speed.
Default planner 1500 ms; record actual hardware/provider cost.

**Demo timing profile (measured 2026-09-26, AUD-022).** The contract waits
out the whole commit window, so a round lasts the commit window plus the
reveal latency (a median 4 ticks in the live arena). The live demo arena on
24/12 ticks resolves a round every 28 ticks: a ranked fight takes a median
80 ticks, 120 s at 1.5 s per tick (143 finished ranked fights in the live
export). The devnet profile `demo-c2` sets timing profile 1 to **commit 9,
reveal 6 ticks**. On the simulated chain (latency 1-3 ticks, 2% drops, the
default demo lineup plus four competent bots, candidate 2, 3,000 ticks) a
ranked fight then takes a median **37 ticks = 55.5 s** and p95 39 ticks = 58.5 s
(104 fights; 24/12 on the same harness with candidate 1: median 56, p95 84 ticks).

| Commit / reveal ticks | Median | p95 | Note |
|---|---:|---:|---|
| 24 / 12 (live, candidate 1) | 120 s | 126 s | live export |
| 10 / 6 | 60 s | 63 s | simulated chain, 60-stamina trial |
| 9 / 6 (chosen) | 55.5 s | 58.5 s | simulated chain, final candidate 2 |
| 8 / 6 | 51 s | 54 s | simulated chain, 60-stamina trial |

A 9-tick commit window leaves a planner about 6 ticks (9 s) before its
commit must be sent, allowing 3 ticks of inclusion latency. In-process
policies need well under a second. An LLM planner must be given a budget of
at most about 7 s (lineup `budget_ms` about 7000 and the model's `--timeout`
about 6), or it misses commits and forfeits. The site's beat-by-beat
playback (6 × 600 ms) fits inside the 13.5 s window.

Stress simultaneous resolutions, cups and ranked queue occupancy. Benchmark
the pinned contract's procedure work AND state hashing, idle hooks, negative
paths, nonce/credit tables and ownership queries. Empty ticks must not scan
historic fights. Full capacity must reject new entry cleanly.

## 5. Money model

For a decisive paid fight with equal stake S and rake fraction r:
gross=2S; net winner credit=2S-floor(2S*r).
For an identical-stake series apply rake once to its total purse.
Draw/void refunds yield zero game rake. There is no default subsidy/bond.

Expected player net for one fight, ignoring execution/provider costs:
p_win*(S-rake) - p_loss*S; draw returns stake.
For equal skill with no draws, expected loss is half the rake. Improvement
can raise a particular player's share; all players cannot profit from the
same unsubsidized purse. Never promote the game as guaranteed earnings.

House operating net =
house rake allocation
- actual execution/state cost paid from house earnings
- hosting/indexing/archival costs
- explicit NPC/exhibition expense
- explicit sponsorship/subsidy.

Registration proceeds, execution-reserve capital, fighter resale and sponsorship
are separate categories. A pre-funded reserve does not remove recurring
consumption. The shareholder pool and developer allocation are not house margin.

Sweep: stake tiers, rake 0..1000 bps, draw/forfeit frequency, users 2..1000,
queue/rating spread, per-user compute costs, peak capacity and NPC demand.
Measure affordable useful tiers from costs; do not infer a production fee from
the 1,000-QU development fixture.

## 6. Farming and adversarial participation

Simulate coordinated fighters, fresh registrations, deliberate losses,
ownership transfers, repeated duels, queue sniping, false affiliation,
stalling draws, reveal withholding, expired offers, and provider crashes.

Operator net =
combat credits + refunds + resale receipts
- stakes/entry fees - acquisition - operating costs.
Report unsold fighters separately. Registration cost may be partly recovered
on resale; do not count it as fully burned capital by assumption.

Measure rating/season manipulation independently of monetary profit.
No-rake draws and low-rake collusive fights can transfer rating or create
qualification. Test pair caps, unique-opponent requirements, known-owner
exclusions and idle expiry without claiming sybil resistance.

NPC wins produce no external rating, prizes or tradable progress.
A paid-NPC proposal requires a separate bounded house-loss model; it cannot
reuse free-practice validation as proof of safe sponsorship economics.

## 7. Acceptance report

Check in: candidate digest, code commits, hardware, seeds, policy/source
versions, budgets, complete matrices, uncertainty method, all failures and
the resulting decision. Distinguish mechanical correctness, measured strategy,
internal usability and external demand. No external demand data exists merely
because operator bots fight each other.

Numeric balance changes require a new candidate/version and regenerated
independent fixtures. Paid activation requires all hard gates passed and
the chosen manifest cost/timing/capacity values justified by the report.

## 8. Balance measurements: candidate 1 and candidate 2

Measured 2026-09-26 for AUD-021 and AUD-022. Two instruments:

- **The campaign** (`scripts/combat-validation.py --ruleset …`, full
  budgets, both rulesets on the same fresh seed suite `holdout-20260926b`).
  Candidate 2's report: [validation-report-candidate-2.md](validation-report-candidate-2.md).
- **A field tournament**: a fast integer simulator (checked against
  `combat/engine.py` on random beats) re-implementing the live arena's
  non-LLM families (random, jabber, kicker, turtle, mixed, scout,
  reader-v1, repeat-last-winner, search-v1, script-vs-mixed,
  script-vs-scout), all history-aware as fixed by AUD-014; 55 pairings ×
  40 paired seeds = 4,400 fights per ruleset. It stands in for the live
  field; it is not a gate. LLM planners are not in it.

### 8.1 Gates (campaign, same seeds)

| Gate | Candidate 1 | Candidate 2 |
|---|---|---|
| Simple strategies with a counter | 29/29 | 29/29 |
| Planner vs random / fixed styles (best) | search-v1 0.914 / 0.980 | search-v1 0.811 / 0.869; reader-v1 0.794 / 0.989 |
| Resource/opening ablation (predictable pool) | +0.175 (LB 0.138) PASS | **−0.002 (LB −0.022) FAIL** |
| History ablation (predictable pool) | +0.106 (LB 0.068) | +0.351 (LB 0.301) |
| Competitive plans from different beliefs | 10 | 10 |
| Draws | 7.4% | 2.6% |
| Fights reaching round 2 | 76.5% | 97.6% |
| Round-0 knockouts | 0.0% | 0.0% |
| Trailing after round 0 wins | 26.9% | 31.2% |
| Exhausted beats (competent) | 1.4% | 2.7% |
| Families ≥ 0.45 vs the pool | scout 0.681, search 0.652, reader 0.647 | reader 0.646, search 0.610, scout 0.576 |
| **Gates passed** | **11/11** | **10/11** |

**The failed gate is a ceiling, and the reason it is not waived.** Against
the predictable pool (fixed styles and scripts) both the full reader and
its no-resource ablation score 0.98-0.99 under candidate 2, so no
difference can show. Against the competent pool (mixed-v1, scout-v1,
repeat-last-winner; 80 paired seeds × 3 = 240 pairs, suite
`ablc-holdout-20260926b`) resources still matter: candidate 2 +0.055
(LB +0.018), candidate 1 +0.094 (LB +0.057). That is a real cost of the
design: a cheap jab that wins the kick exchange makes stamina planning
less decisive. A 60-stamina trial of candidate 2 measured only +0.035
(LB −0.023) there; the 48-stamina cap is what brings it back above 0.05.
Candidate 1's first campaign met the same ceiling on the history gate and
fixed it with harder predictable opponents; the same instrument fix
(scripts computed against the reader, or the competent pool for this
ablation) is the next step, and it is a gate change for the reviewers to
decide, not something to adopt after seeing the result. Until then the
resource gate is a **FAIL** for candidate 2, which blocks paid activation
under §7, not the fake-QU demo arena.

### 8.2 Fight shape and action value (campaign, competent pool)

| Measure | Candidate 1 | Candidate 2 |
|---|---:|---:|
| KO / decision / draw | 72.5% / 27.5% / 7.4% | 43.9% / 56.1% / 2.6% |
| Executed beats per fight | 14.8 | 16.8 |
| Leader after round 1 (of 0..2) wins | 78.0% | 78.9% |
| Opening + power bonus per fighter and fight | 1.9 + 1.7 HP | 5.8 + 6.9 HP |
| Net HP per beat: KICK / JAB / THROW | +6.56 / +1.03 / −0.84 | +5.58 / +3.74 / +0.62 |
| Net HP per beat: BLOCK / DUCK / RECOVER | −1.19 / −4.51 / −8.61 | −1.98 / −2.52 / −8.62 |
| Share: JAB / KICK / BLOCK / DUCK / THROW / RECOVER | 22 / 26 / 14 / 14 / 8 / 15% | 25 / 19 / 13 / 15 / 9 / 16% |

Net HP per beat favours attacks by construction (BLOCK and DUCK deal
nothing except the duck counter; RECOVER buys stamina). What matters is
the spread between the attacks and whether the defences lose less:
KICK's lead over JAB fell from 5.5 to 1.8 HP per beat, THROW turned
positive, DUCK's loss halved.

### 8.3 The live-field tournament

| Measure (4,400 fights each) | Candidate 1 | Candidate 2 |
|---|---:|---:|
| KO / decision / draw | 82% / 17% / 5% | 64% / 35% / 2% |
| Fights reaching round 3 | 54% | 89% |
| Trailer after the first round wins | 20% | 26% |
| Leader after the second round wins | 84% | 86% |
| Median final HP margin; finishes within 8 HP | 28; 18% | 36; 14% |
| Opening + power bonus per fighter and fight | 2.9 HP | 12.5 HP |
| Net HP per beat KICK / JAB / THROW / BLOCK / DUCK | +7.2 / +1.5 / +1.9 / −1.3 / −5.6 | +5.4 / +4.2 / +3.2 / −2.0 / −3.3 |
| One-beat equilibrium at a fresh state (value 8×HP + stamina) | KICK 50%, BLOCK 49% | JAB 32%, KICK 20%, BLOCK 35%, DUCK 13% |
| History value: reader minus history-blind reader | +0.05 | +0.31 |
| Top of the field | script-vs-scout 0.84, reader 0.83, search 0.79 | reader 0.85, search 0.71, jabber 0.70 |
| reader-v1's own mix J / K / B / D / T / R | 20 / 33 / 12 / 10 / 13 / 11% | 32 / 18 / 7 / 15 / 14 / 12% |

Readings:

- **No dominant action.** KICK no longer weakly dominates JAB; four
  actions carry the one-beat equilibrium; the best planners use every
  action. THROW stays situational (best reply on 29% of beats, against
  blocks and recoveries, played on 6-14%) and RECOVER is a resource move.
- **Adaptation pays more.** A fixed script topped candidate 1's field; in
  candidate 2 the history-aware reader leads and the best script is fifth.
  The round-by-round swing of the adapters grew (reader-v1's HP differential: −5.9 in the first round, +49.6 in
  the second; candidate 1: −11.2 and +36.8).
- **Fewer knockouts, more full fights.** Round 3 is reached in 89% of fights.
- **Not improved: late comebacks and close finishes.** The leader after the second round
  still wins about 86%, and better planners win by wider margins. The field
  policies do not change risk with the score; comebacks may need a mechanic
  (see AUD-021's proposals) rather than numbers.
- **Style readability.** Jabber beats kicker 1.00 and both scripts; kicker
  (kick, recover, repeated) now loses to every adapter, because the jab
  answers the kick and punishes the recovery.

### 8.4 Rejected variants

About fifty variants were measured on the field tournament before the
campaign (details in [AUD-021](../audits/issues/AUD-021-balance-kick-duck.md)).
Single levers on candidate 1 (kick cost 14, kick 10 damage, throw 20,
duck counter, power 10, opening 8) left KICK/BLOCK the only equilibrium.
Jab-wins-kick was the necessary change; HP 120 cut KOs; throw 20, duck
counter 4, opening 8 and power 12 each helped a little; block cost and
strain changes did nothing measurable. Rounds × beats of 8×3, 6×4, 5×4
and 4×4 (HP scaled) did not improve comebacks or history value, widened
margins and raised exhaustion to 10-11% with 8-beat rounds
([combat.md §11.5](combat.md#115-considered-and-not-adopted)).
