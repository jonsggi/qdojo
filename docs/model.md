# Combat validation and economics

> **Purpose:** the acceptance gates combat must pass: correctness, exploits, optimisation reward, fight shape, readability, timing, money and farming. \
> **Audience:** reviewers deciding whether the ruleset is fit to launch. \
> **Status:** normative (the gates). It defines measurements and claims none. Results so far are in [validation-status.md](validation-status.md): mechanical correctness and the 11 strategic gates measured so far pass on held-out seeds. Not measured: adaptation time against a style-switching opponent, §3 readability, §4 timing and contract cost, and economics with real costs. \
> **Last reviewed:** 2026-09-25 (header, status and links; rules text unchanged)

Historic riddle experiments are [archived](archive/riddle-v0/docs/model.md) and are not combat evidence.

## Contents

- [1. What success must mean](#1-what-success-must-mean)
- [2. Required experiments](#2-required-experiments)
- [3. Human readability and bot development](#3-human-readability-and-bot-development)
- [4. Timing and compute](#4-timing-and-compute)
- [5. Money model](#5-money-model)
- [6. Farming and adversarial participation](#6-farming-and-adversarial-participation)
- [7. Acceptance report](#7-acceptance-report)

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
