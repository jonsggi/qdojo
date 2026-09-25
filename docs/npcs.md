# NPCs, practice and benchmark opponents

> **Purpose:** the six disclosed practice opponents, their exact policies, and the reproducible training randomness. \
> **Audience:** bot builders; implementers of NPC ports. \
> **Status:** normative (combat-v1 candidate 1). Implemented in `combat/npcs.py`; the browser port (`apps/web/combat/npcs.js`) matches 900 frozen plan fixtures. `qdojo combat npcs` lists them. \
> **Last verified:** 2026-09-25 (roster and CLI; policy text unchanged)

They are real bot policies choosing legal hidden plans through the same combat
interface. They are not pre-scripted outcome animations.

## 1. Product modes

- **Local practice:** immediate, free, offline, no NFT/wallet/node/signing.
  Human selects an NPC, ruleset and optional replayable seed.
- **Public exhibition:** disclosed house NPC against a willing fighter,
  zero stake, no rating/season/trophy credit. May use the full contract
  commit/reveal path to demonstrate verification; operator funds execution.
- **Ranked:** independent eligible fighters only. Never silently fill the
  ranked queue with an NPC. An idle queue can offer a separate Free sparring button.

Paid NPC fights and NPC-filled prize cups are outside v1. If added later, require
explicit opt-in, disclosed house affiliation, separately funded liability and
measured exploit/subsidy budgets. Do not label house funds as external demand.

Practice profiles use synthetic local fighter IDs and identical combat stats.
An NPC never receives extra HP, perfect foresight, secret opponent history or
a move that players cannot use. Difficulty comes from policy quality.

## 2. Required initial roster

Names below are working labels; IDs and versions are stable.

| ID | Behavior | Intended lesson |
|---|---|---|
| random-v1 | Uniform independent actions, optional random power timing | Learn rules; benchmark against an unstructured opponent |
| jabber-v1 | JAB,JAB,JAB,RECOVER,JAB,JAB each round | Punish predictable highs with duck/counter |
| turtle-v1 | BLOCK,BLOCK,RECOVER,BLOCK,DUCK,RECOVER | Use throw, low attacks and guard pressure |
| kicker-v1 | KICK,RECOVER,KICK,RECOVER,KICK,RECOVER | Punish expensive attacks and recovery timing |
| mixed-v1 | Stateful weighted policy, described below | Test basic resource-aware optimization |
| scout-v1 | Adapt next-round action distribution from past observations | Train against an opponent that changes strategy |

Fixed-pattern profiles use power on the first attack in round 2 (zero-indexed),
if still available; otherwise unused. They still pay normal costs and may
exhaust themselves. Don't repair their mistakes with a hidden advantage.

random-v1 independently samples each of six action IDs uniformly from 0..5.
Then uniformly selects power_slot from [unused] plus every attack slot, if
power remains available. No stamina filter. This deliberately simple baseline
can make bad choices; it should not be advertised as optimal random play.

mixed-v1 weights at each planned beat in J,K,B,D,T,R order are [3,2,2,2,1,2].
Before sampling, simulate the partial plan against RECOVER-only using the exact
engine to estimate its own resources. Clamp projected HP to at least 1 only
when filling the remaining hypothetical plan slots, as described for scout-v1. If projected stamina<12, use
[1,0,2,2,0,5]. This is explicitly a prediction, not knowledge of the opponent.
Do not remove exhaustion behavior from actual settlement. Reserve power for
round 2, first selected attack with predicted stamina >= cost+4.

scout-v1 starts with mixed-v1. At the end of each actual round, count the
opponent's EXECUTED effective actions, with one pseudocount for each legal
action; omit EXHAUSTED. Aggregate that fight's prior rounds only.
For next round, evaluate each candidate next action against that distribution
using exact one-beat resolution from projected states:
score = 4*(expected outgoing damage - incoming damage)
        + expected stamina change.
Choose a maximizing action with probability 3/4; otherwise sample mixed-v1.
Break equal scores by seeded uniform selection. Update projected state against
the distribution's modal action (ties lowest action ID). Carry the real start
state into each new round. For projected planning only, keep either predicted
HP at a minimum of 1 when continuing to fill remaining slots; this prevents
a projected KO from shortening the required six-action plan. Actual combat
always uses the real KO rule.

scout-v1 uses the same power reservation rule as mixed-v1. Its expectation
uses rational integer sums: compare unnormalized weighted scores over the
common total count, without floating point; evaluate candidate actions with
no power bonus. Sample its 3/4 choice with uniform(4)<3. Modal opponent
projection does not spend opponent power. Recompute each candidate from
the same projected snapshot; choosing one candidate must not mutate the
snapshots used to score others. Fix and publish this heuristic version; it is a
reference opponent, not a claim of optimal play.

## 3. Reproducible randomness

Practice/benchmark seeds are 32 bytes. PRNG stream:
SHA256(ASCII "qdojo/npc/v1\0" || seed[32] || fight_number u64 LE ||
round_index u8 || block_counter u32 LE), concatenated for counters 0,1,2...
Consume bytes in order; for uniform n in 1..256, discard bytes >=
256-(256 mod n), then use byte mod n. Weighted draws use a uniform integer
below the sum of integer weights and cumulative buckets in action-ID order.

Record NPC policy version, seed and ruleset in local practice results.
For hosted exhibitions, keep the match seed private until the fight ends,
then optionally publish it for reproducibility. A production salt for commitments
is independent cryptographic randomness, never this training PRNG.

The hosted NPC service runs off chain and signs its own commitments/reveals.
It uses only the same public observation supplied to a player bot. Contract
storage is public, so do not attempt to keep its unrevealed plan or private seed
inside the smart contract. The contract never calls an NPC model or trusts an
NPC's claimed outcome.

## 4. Training reports and evaluation

Show per-NPC score (win=1, draw=0.5), uncertainty, mean HP difference,
exhausted beats, wasted power, recovery punishments, guard failures and change
since the previous bot version. Split opponent/policy versions and seeds.

Freeze evaluation seeds independently from training. Report performance on
unseen seeds AND held-out opponent policies. Beating random-v1 alone is a
beginner milestone; it does not establish competitive strength or balance.

Provide side-swapped paired trials, reproducible replays, batch evaluation,
private opponent-model storage and a configurable per-decision compute budget.
Practice rewards are local achievements only: no ranked points, QU,
tradable rewards or combat-stat upgrades that can be farmed by resetting NPCs.
