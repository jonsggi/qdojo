# Combat rules: combat-v1 candidates 1 and 2

> **Purpose:** every mechanical rule: state, actions, the damage matrix, exact beat resolution and hand-checkable vectors. \
> **Audience:** bot builders who want exact numbers; implementers; reviewers. Scope and money are in [spec.md](spec.md). \
> **Status:** normative. Sections 1-10 are candidate 1 ([combat-v1.json](combat-v1.json), digest `12085c86…`); [section 11](#11-candidate-2) is candidate 2 ([combat-v1-candidate-2.json](combat-v1-candidate-2.json), digest `231607f8…`): the same engine and encodings with rebalanced numbers. Both are implemented in Python (`combat/engine.py`), C++ (`contracts/combat_core/`, one table per candidate) and the browser (`apps/web/combat/engine.js`); all three agree on 10,000 frozen fights per candidate. The §5 and §11.2 matrices are machine-checked against their JSON files by `docs/reference/check_docs.py`. Balance: see [validation-status.md](validation-status.md) and [model.md §8](model.md#8-balance-measurements-candidate-1-and-candidate-2). \
> **Last verified:** 2026-09-26 (§8 and §11.3 vectors run in the test suite)

## Contents

- [1. Design contract](#1-design-contract)
- [2. State and constants](#2-state-and-constants)
- [3. Plan format](#3-plan-format)
- [4. Moves](#4-moves)
- [5. Complete damage matrix](#5-complete-damage-matrix)
- [6. Exact beat resolution](#6-exact-beat-resolution)
- [7. Exact round and fight pseudocode](#7-exact-round-and-fight-pseudocode)
- [8. Hand-checkable acceptance vectors](#8-hand-checkable-acceptance-vectors)
- [9. Trace and explanation requirements](#9-trace-and-explanation-requirements)
- [10. Bot optimization and uncertainty](#10-bot-optimization-and-uncertainty)
- [11. Candidate 2](#11-candidate-2)

## 1. Design contract

A fighter submits six actions at once. Both plans are hidden until both
commitments are fixed. Resolve paired actions simultaneously, then publish
the full round. Bots choose a new plan for the next round using its actual
result. They cannot branch or substitute actions within a submitted plan.

Three rounds create eighteen possible beats. Knockout may end a fight sooner.
Health never resets between these rounds. Every new fight in a series starts
from the same initial state.

Strategic depth comes from resource budgeting, predicting actions, exploiting
recovery, counter opportunities, guard fatigue, a limited power strike and
adapting between rounds. Surprises come from concealed plans and privately
randomized bot decisions. There is NO settlement RNG, critical-hit roll,
house-selected modifier, comeback damage multiplier or hidden damage rule.

These choices create hypotheses about engagement, not proof of lasting depth.
Ship only after the adversarial evaluation in [model.md](model.md).

## 2. State and constants

Per fighter:

| Field | Initial value | Range / meaning |
|---|---:|---|
| hp | 100 | Integer 0..100 |
| stamina | 60 | Integer 0..60 |
| opening | 0 | Boolean opportunity: +4 damage on the next beat only |
| guard_streak | 0 | Consecutive effective BLOCKs, saturated at 3 |
| power_available | 1 | One optional power strike per fight |

Global state: fight ID, ruleset digest, round index 0..2, beat index 0..5,
fighter slots A/B. Slot A is the lexicographically smaller fighter ID, compared
as unsigned bytes. Slot ordering affects serialization only, never initiative.

Inter-round recovery is +10 stamina, capped at 60, applied once after a
nonterminal round 0 or 1. HP, opening, guard_streak and power_available carry.
No regeneration occurs because a bot/chain is slow, a replay is paused,
or more real time passes.

Final outcome: if one HP is zero, other wins; if both zero, simultaneous-KO
draw; otherwise after round 2 compare HP, higher wins; equal HP is a draw.
Do not break ties with stamina, power, rating, commit tick or chain ordering.
No extra combat rounds in a ranked fight.

## 3. Plan format

Logical JSON (wire encoding belongs to [protocol.md](protocol.md)):

```json
{
  "actions": ["JAB", "DUCK", "KICK", "RECOVER", "BLOCK", "THROW"],
  "power_slot": 2
}
```

Exactly six actions. power_slot is -1 (unused this round) or 0..5.
A nonnegative slot MUST select JAB, KICK or THROW and the fighter must have
power_available=1 at round start. Power is optional in every round, including
the last. A submitted action is still legal when unaffordable; exhaustion
has a defined in-game result below.

The entire plan is validated before any combat, including beats after a
possible knockout. Unknown action, extra action, invalid power slot or
already-spent power makes that reveal invalid. No silent truncation or repair.

## 4. Moves

| ID | Action | Cost | Purpose and weakness |
|---|---|---:|---|
| 0 | JAB | 6 | Efficient high attack; fails against block/duck |
| 1 | KICK | 12 | Low attack; punishes duck, drains block; costly |
| 2 | BLOCK | 4 + 3*guard_streak | Stops strikes; loses to throw and repeated use drains stamina |
| 3 | DUCK | 4 | Evades jab/throw and earns opening; vulnerable to kick |
| 4 | THROW | 9 | Beats block/recovery; interrupted by jab/kick, evaded by duck |
| 5 | RECOVER | 0 | Restores stamina; exposed to damage and reduced recovery if hit |
| internal 6 | EXHAUSTED | 0 | Failed unaffordable move; exposed, limited recovery |

EXHAUSTED cannot appear in a submitted plan. Cosmetic animations, movement
speed and sprite hitboxes never change these rules. There is no distance,
facing, jump, stun, knockdown or interrupt carry-over in v1.

## 5. Complete damage matrix

Each cell is damage dealt BY the row action TO the column action, before
opening/power. The other fighter's damage is the transposed lookup.
Read both from the same pre-damage state; never update A before looking up B.

| Attacker / defender | JAB | KICK | BLOCK | DUCK | THROW | RECOVER | EXHAUSTED |
|---|---:|---:|---:|---:|---:|---:|---:|
| JAB | 8 | 8 | 0 | 0 | 8 | 12 | 12 |
| KICK | 14 | 14 | 0 | 18 | 14 | 18 | 18 |
| BLOCK | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| DUCK | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| THROW | 0 | 0 | 14 | 0 | 0 | 18 | 18 |
| RECOVER | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| EXHAUSTED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Consequences:

- Jab/block: neither loses HP.
- Jab/kick: both take damage even if one will be knocked out.
- Throw/throw: both fail; both pay.
- Block/kick: no HP damage; block suffers six extra stamina drain.
- Duck/throw: throw fails and duck earns an opening.
- Recovery's vulnerability is already included in the matrix.
- Power/opening do not turn a zero cell into damage.

Do not add another recovery vulnerability bonus outside this matrix.

## 6. Exact beat resolution

Inputs: BOTH fighters' pre-beat states, intended actions and whether this is
their designated power slot. Always compute the paired changes from snapshots.

1. **Determine cost.** Use the table and pre-beat guard_streak. A designated
   power strike adds 4 stamina to its attack's cost.
2. **Spend power.** If this is the designated slot, set power_available to 0.
   It is spent even if the move will be blocked, dodged, interrupted or exhausted.
   A slot after a knockout is never executed and consumes nothing.
3. **Choose effective action.** If pre-beat stamina is at least full cost,
   execute intended action and subtract that full cost. Otherwise execute
   EXHAUSTED, subtract no stamina, and record intended action/cost plus
   reason INSUFFICIENT_STAMINA. No cheaper fallback attack.
4. **Look up both base damages** using effective actions.
5. **Apply bonuses.** If own base damage >0, add 4 if own pre-beat opening=1;
   add another 4 if this was own designated power slot and the effective
   action is its intended attack. Bonuses stack additively. If base is 0,
   damage stays 0; opening/power can be wasted.
6. **Apply damage simultaneously.** Subtract the other fighter's final damage,
   clamped at 0 HP. Report full computed damage and actual HP lost separately.
7. **Apply block strain.** If own effective action is BLOCK and opponent's
   effective action is KICK, subtract an additional 6 stamina, clamped at 0.
   The current block still succeeds even when strain empties stamina.
   Power does not increase strain.
8. **Recover stamina.** Effective JAB/KICK/BLOCK/DUCK/THROW gain 2. RECOVER
   gains 18 when incoming computed damage is 0, otherwise 6. EXHAUSTED gains
   6, whether hit or not. These values are alternatives; never add the +2
   passive gain to RECOVER or EXHAUSTED. Cap at 60.
9. **Replace opening.** Old opening expires on this beat regardless of action.
   New opening is 1 exactly when either:
   (a) own effective DUCK faced effective JAB or THROW; or
   (b) own effective JAB dealt positive damage and incoming damage was 0.
   Otherwise it is 0. Damage modifiers do not add another opening.
10. **Replace guard streak.** Effective BLOCK sets
    min(3, old_guard_streak+1); every other effective action sets 0.
11. **Emit trace and check knockout.** Finish all paired updates first.
    If either HP=0, mark terminal and skip remaining beats. Otherwise continue.

Opening does not interrupt an attack. A clean jab can create a follow-up,
but that follow-up still loses to an appropriate defense. Opening can carry
from beat 5 into the next round's beat 0, through the fixed recovery break.

## 7. Exact round and fight pseudocode

```text
resolve_round(start, plan_A, plan_B):
    require start is nonterminal and round_index in 0..2
    validate both complete plans against start
    state = copy(start)
    for beat in 0..5:
        old_A, old_B = snapshots(state)
        intent_A = plan_A.actions[beat]
        intent_B = plan_B.actions[beat]
        next_A, next_B, trace = resolve_beat_from_snapshots(...)
        assign both next states
        append trace
        if either hp == 0:
            return terminal outcome from both hp values
    if round_index == 2:
        return terminal outcome by hp comparison
    for fighter in both:
        fighter.stamina = min(60, fighter.stamina + 10)
    round_index += 1
    return new round-start state, traces, explicit break-recovery event
```

A forfeit is a protocol result, not an invented combat knockout. Never fabricate
unplayed beats or zero the forfeiter's HP for the animation.

No state depends on a global random generator, clock, floating point,
transaction ID order or rendering timestep. Integer intermediates must be wide
enough to avoid overflow before clamping. Reject an impossible input state;
do not repair malformed saved state by clamping it into plausibility.

## 8. Hand-checkable acceptance vectors

These are normative arithmetic examples. Unless specified: both have HP=100,
stamina=60, opening=0, guard_streak=0, power_available=1. Fields below describe
AFTER ONE BEAT, before any round-break recovery.

| A / B | A (HP, stamina, opening, guard_streak) | B (HP, stamina, opening, guard_streak) |
|---|---|---|
| JAB / BLOCK | (100,56,0,0) | (100,58,0,1) |
| JAB / KICK | (86,56,0,0) | (92,50,0,0) |
| DUCK / JAB | (100,58,1,0) | (100,56,0,0) |
| KICK / DUCK | (100,50,0,0) | (82,58,0,0) |
| THROW / BLOCK | (100,53,0,0) | (86,58,0,1) |
| BLOCK / KICK | (100,52,0,1) | (100,50,0,0) |
| RECOVER / JAB | (88,60,0,0) | (100,56,1,0) |
| THROW / THROW | (100,53,0,0) | (100,53,0,0) |

Additional stateful vectors:

- After DUCK/JAB above, play KICK/JAB: A=(92,48,0,0);
  B=(82,52,0,0). A's kick dealt 18 due to its opening.
- A has stamina=11 and attempts KICK against B's JAB:
  A effective EXHAUSTED, A=(88,17,0,0), B=(100,56,1,0).
- A has stamina=12 and attempts KICK (whatever B plays): it executes, ending stamina=2.
- A at stamina=60, opening=1 uses powered KICK into DUCK:
  A stamina=46, power_available=0; B loses 26 HP; no other damage.
- Powered JAB into BLOCK: A stamina=52, power_available=0, no HP loss.
- A with stamina=9 attempts powered JAB into JAB: cost=10, so EXHAUSTED;
  A loses 12 HP and ends stamina=15; power_available=0.
- Four consecutive BLOCKs against RECOVER leave the blocker at stamina
  58, 53, 45, 34 and guard_streak 1,2,3,3. A fifth costs 13 again.
- BLOCK at stamina=4 into KICK succeeds: pays 4, strain clamps to 0,
  recovers to 2, HP unchanged. The next BLOCK costs 7 and is unaffordable.
- A and B at HP=8 both JAB: simultaneous KO draw; both deal 8.
- A HP=14, B HP=8, A JAB/B KICK: simultaneous KO draw.
- Both submit six RECOVERs in each of three rounds: HP stays 100,
  stamina stays 60, outcome HP_TIE draw. No fees or win points.
- Both submit six JABs for round 0 with no power: HP=52 each,
  stamina=36 before break and 46 after break; opening=0.
  Repeat six JABs in round 1: HP=4, stamina=22 before break,
  32 after break. Round 2 first JABs cause a simultaneous KO;
  later intended actions are revealed but not executed.
- Ending round 0 with stamina=55, opening=1, guard_streak=3 results
  in next round stamina=60, opening=1, guard_streak=3. (This is a break-rule
  check on a hypothetical state: one fighter cannot end a beat with both an
  opening and a guard streak, because a streak needs BLOCK and an opening
  needs DUCK or JAB. Tests check each carry separately in playable rounds.)
- Power at a planned slot after an earlier KO is marked unexecuted.
  It is not charged and does not create damage or a third-round action.

Implement all examples in independent Python and C++ fixtures. Add a browser
reader against the same fixture bytes. Generate full-round fixtures only after
independent hand vectors pass. Do not regenerate expected values from a failing
implementation just to make its tests green.

## 9. Trace and explanation requirements

Per executed beat publish pre/post states, intended and effective actions,
power flag, action cost actually paid, base damage, opening/power bonus,
computed damage, actual HP lost, block strain actually deducted, recovery,
new opening and reason codes. Always preserve A/B orientation.

Stable reason codes include:
HIT, BLOCKED, EVADED, THROW_INTERRUPTED, THROW_CLASH, INSUFFICIENT_STAMINA,
RECOVERY_PUNISHED, GUARD_STRAIN, OPENING_EARNED, OPENING_USED,
OPENING_EXPIRED, POWER_USED, POWER_WASTED, KO, DOUBLE_KO.
Multiple codes may describe a beat; do not use a reason code as hidden logic.

Codes are attached per side, in this order (the Python, C++ and browser
engines agree on all 10,000 frozen fixture fights):

1. INSUFFICIENT_STAMINA when the effective action is EXHAUSTED.
2. HIT when this side's computed damage is positive; otherwise, for an
   effective attack: THROW_CLASH (throw vs throw), THROW_INTERRUPTED
   (throw vs jab/kick), BLOCKED (vs block), EVADED (vs duck).
3. RECOVERY_PUNISHED when an effective RECOVER takes positive damage.
4. GUARD_STRAIN when an effective BLOCK meets an effective KICK, even if
   the strain actually deducted is 0.
5. OPENING_USED (pre-beat opening and positive base damage) or
   OPENING_EXPIRED (pre-beat opening otherwise).
6. POWER_USED (designated slot, executed as intended, positive base damage)
   or POWER_WASTED (designated slot otherwise).
7. OPENING_EARNED when the new opening is 1.
8. KO on the side knocked out alone; DOUBLE_KO on both sides.

The trace's `recovered` and `strain` fields are the amounts actually applied
after the zero clamp and the stamina cap, not the nominal values.

A useful explanation is: "Your kick cost 12; you had 11, so you were exposed
and took 12 from the jab." Show the numbers and the alternative only after
resolution. Label counterfactuals against the recorded plan as hindsight,
not proof that the opponent would have played the same way.

Preserve all six revealed intended actions even if KO stops execution; label
the unused suffix. Distinguish observed play from unexecuted intentions in
training statistics. A terminal missing reveal has no fabricated plan.

## 10. Bot optimization and uncertainty

Owners may retain private opponent models, randomize with private seeds, search
sequences, train on public history and change software between rounds. Only
the selected action sequence/power slot becomes public. Never require source,
model weights or random seeds to be published.

Do not publish live commitments' plaintext plans in logs, analytics or previews.
Opponent scouting uses completed rounds, including earlier rounds of this fight.
Previous-round data is available before the next commitment window starts.

With six actions there are 46,656 unpowered sequences per round. Power timing
expands the choices, but large combinatorics alone does not establish depth.
Search quality, resource accounting, uncertainty calibration and opponent
adaptation are the intended engineering opportunities. A simple mixed policy
may be strong; test that instead of assuming complexity wins.

Do not reward hidden rubber-banding or purchased advantages to manufacture
surprise. If the metagame converges prematurely, change the candidate rules
and rerun evaluation before launch. Later reviewed mechanics need explicit
state/cost/counterplay, fixed integer resolution, bounded work, equal access
and a new ruleset version.

## 11. Candidate 2

`combat-v1-candidate-2`, digest
`231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b74`,
file [combat-v1-candidate-2.json](combat-v1-candidate-2.json).

Candidate 2 changes numbers only. Sections 1-4 and 6-10 apply unchanged:
the same six actions and ids, three rounds of six beats, the 7-byte plan
and 8-byte state encodings, the step order of §6, the opening rules, the
reason codes and the round pseudocode. Candidate 1 stays frozen and
loadable: every fight names the digest it was played under, and its
replays verify under that ruleset.

### 11.1 Changes from candidate 1, and why

| Change | Candidate 1 | Candidate 2 | Why (measured with candidate 1, [model.md §8](model.md#8-balance-measurements-candidate-1-and-candidate-2)) |
|---|---:|---:|---|
| JAB vs KICK exchange (jab deals / kick deals) | 8 / 14 | 10 / 4 | KICK weakly dominated JAB in every matrix column, earned +7.2 HP per beat, and the one-beat equilibrium was KICK and BLOCK only. The jab is now the fast answer to a kick: a read, where it used to be a losing trade. |
| DUCK vs JAB (duck deals) | 0 | 4 | DUCK was the worst action (−5.6 HP per beat). Slipping a jab now counters for 4 as well as earning the opening. DUCK is still not an attack: it cannot carry power. |
| THROW vs BLOCK | 14 | 20 | Throw is the only answer to a turtle; it now punishes a predicted block harder. |
| Opening bonus | 4 | 8 | Power and opening together added about 3 HP per fighter and fight, too little to plan around. |
| Power bonus | 4 | 12 | The same reason. Power still costs +4 and is spent even if it misses. |
| Initial and maximum HP | 100 | 120 | With the stronger reads, 100 HP made about 87% of fights knockouts; 120 brings it to about 68%. |

Everything else is unchanged: costs, block streak cost and strain,
recovery, break recovery, stamina limits, rounds and beats.

Consequences in words:

- Jab/kick: both land, but the jab wins 10 to 4 and the kick costs twice as much.
- Kick/kick: 14 each, as before. Kick still punishes duck and recovery for 18.
- Duck/jab: the jab deals 0, the duck deals 4 and earns an opening
  (reason codes: HIT and OPENING_EARNED for the duck, EVADED for the jab).
  With an opening already in hand the counter deals 4 + 8 = 12.
- Throw/block: 20. A powered throw into a block deals 32.
- A powered kick into a duck with an opening deals 18 + 8 + 12 = 38.

### 11.2 Damage matrix

| Attacker / defender | JAB | KICK | BLOCK | DUCK | THROW | RECOVER | EXHAUSTED |
|---|---:|---:|---:|---:|---:|---:|---:|
| JAB | 8 | 10 | 0 | 0 | 8 | 12 | 12 |
| KICK | 4 | 14 | 0 | 18 | 14 | 18 | 18 |
| BLOCK | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| DUCK | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| THROW | 0 | 0 | 20 | 0 | 0 | 18 | 18 |
| RECOVER | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| EXHAUSTED | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

State: HP 0..120, starting at 120; stamina 0..60, starting at 60. Opening
+8, power +12 for +4 stamina.

### 11.3 Hand-checkable vectors

Both fighters start at (HP 120, stamina 60, opening 0, guard 0, power 1).
Fields are after one beat.

| A / B | A (HP, stamina, opening, guard_streak) | B (HP, stamina, opening, guard_streak) |
|---|---|---|
| JAB / BLOCK | (120,56,0,0) | (120,58,0,1) |
| JAB / KICK | (116,56,0,0) | (110,50,0,0) |
| DUCK / JAB | (120,58,1,0) | (116,56,0,0) |
| KICK / DUCK | (120,50,0,0) | (102,58,0,0) |
| THROW / BLOCK | (120,53,0,0) | (100,58,0,1) |
| BLOCK / KICK | (120,52,0,1) | (120,50,0,0) |
| RECOVER / JAB | (108,60,0,0) | (120,56,1,0) |
| THROW / THROW | (120,53,0,0) | (120,53,0,0) |

- After DUCK/JAB above, play KICK/JAB: A's kick deals 4 + 8 opening = 12,
  B's jab deals 10. A=(110,48,0,0); B=(104,52,0,0).
- A at stamina 60 with an opening powers a KICK into a DUCK: A stamina 46,
  power spent; B loses 38.
- A with an opening DUCKs a JAB: the counter deals 12; A earns a new opening.
- A at stamina 11 attempts KICK against a JAB: EXHAUSTED, A=(108,17,0,0),
  B=(120,56,1,0).
- Six JABs each per round: HP 72 and stamina 46 after the first break,
  HP 24 and stamina 32 after the second; the third beat of round 2 is a
  simultaneous KO.
- Six RECOVERs each, three rounds: HP stays 120, an HP_TIE draw.

These run in `packages/qdojo/tests/combat/test_candidate2.py`, the C++
build with `-DQDOJO_RULESET=2` and `apps/web/tests/combat-engine.test.cjs`.

### 11.4 Selecting a ruleset

- A devnet or arena fixes its ruleset when it is created. Profile `demo-c2`
  (`combat/devnet.py`) is the demo arena on candidate 2 with the demo
  timing (commit 9, reveal 6 ticks); `demo` and `dev` stay on candidate 1.
- `qdojo combat train` and `qdojo combat evaluate` take `--ruleset`;
  `scripts/combat-validation.py --ruleset` runs the model.md campaign.
- `verify_replay` and `qdojo combat replay` use the ruleset the replay names.
- The C++ core compiles both tables and a build selects one
  (`-DQDOJO_RULESET=2`); a deployed contract serves exactly the ruleset its
  manifest names.
- The site embeds both rulesets and replays with the one whose digest
  equals the export manifest's (the export's own ruleset artifact first).

### 11.5 Considered and not adopted

- **Longer rounds or more rounds** (8 beats × 3 rounds, 6 × 4, 5 × 4, 4 × 4,
  HP scaled): none improved comebacks or adaptation value, blowouts grew,
  exhaustion reached 10-11% in 8-beat rounds, and 6 × 4 adds a fourth
  commit window to every fight. The plan encoding, the contract, the site
  planner and every bot would have had to change for no measured gain.
- **A new move** (FEINT, PARRY, CHARGE): parameter changes gave every
  action a role (model.md §8), so the cost of a new action id was not
  justified. The proposals are recorded in
  [AUD-021](../audits/issues/AUD-021-balance-kick-duck.md).
