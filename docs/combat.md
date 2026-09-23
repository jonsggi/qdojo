# Combat engine: combat-v1 candidate 1

Owner of all mechanical rules. Read [spec.md](spec.md) for scope and money.
Status: specified, not implemented; numerical balance must pass [model.md](model.md).

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
- A has stamina=12 and attempts KICK: it executes, ending stamina=2.
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
  in next round stamina=60, opening=1, guard_streak=3.
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
