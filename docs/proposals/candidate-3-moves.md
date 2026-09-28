# Candidate 3: new moves (proposal)

> **Purpose:** the design and measurement for combat-v1 candidate 3: which new move, its exact rules, and the evidence. \
> **Audience:** the owner; the presentation track (deck, sprites, rules page); implementers of the C++ and browser engines. \
> **Status:** proposal. Measured on a Python-only prototype (trial rulesets `combat-v1-candidate-3-trial-a` and `-trial-b`, branch `work/moves`). Nothing here is deployed, and no C++, browser, site or sprite support exists yet. \
> **Last reviewed:** 2026-09-28

## Contents

- [1. Summary](#1-summary)
- [2. The move: LAST STAND](#2-the-move-last-stand)
- [3. What changes where](#3-what-changes-where)
- [4. Measurements](#4-measurements)
- [5. Moves considered and rejected](#5-moves-considered-and-rejected)
- [6. Risks and open questions](#6-risks-and-open-questions)
- [7. Recommendation](#7-recommendation)

## 1. Summary

Candidate 2 fixed kick dominance but not three things: late comebacks (the
leader after round 2 wins 86% in the live-field simulation), close finishes
(14% within 8 HP), and the model.md gate "resource/opening state matters".

One new move does most of that: **LAST STAND**, a strike that hits harder
the further its fighter trails in HP (+1 damage per HP behind, capped at
+16). It is public, deterministic, equal for both fighters, and countered by
a block, a kick trade or a throw read. It adds one action (id 7): eight
actions including the internal EXHAUSTED, a seventh key on the move deck, and
the same 7-byte plan.

Measured against candidate 2 on the same held-out campaign seeds:

| | Candidate 2 | + LAST STAND, every round (trial b) |
|---|---:|---:|
| Leader after the second round wins (campaign) | 78.9% | **67.8%** |
| Leader after the second round wins (live field) | 86% | **79%** |
| Finishes within 8 HP (live field) | 14% | **25%** |
| Resource/opening ablation gate (needs ≥ 0.05, LB > 0) | +0.031 (LB 0.007) FAIL | +0.047 (LB 0.027) FAIL, nearly |
| Draws / trailer after round 0 wins (bands ≤15%, 10..40%) | 2.7% / 30.7% | 7.6% / 37.3% |
| Gates passed | 10/11 | 10/11 |

**Recommendation:** adopt LAST STAND, active in every round (trial b), as
candidate 3, after the owner accepts the design-contract change in
[§6](#6-risks-and-open-questions). No second or third move: each one measured
alone did less than LAST STAND, and together they cost the eighth action slot.

## 2. The move: LAST STAND

**Deck line:** `LAST STAND · 8 · Strike +1 per HP you trail (max +16). Blocked; a kick out-trades it.`

**Flavour.** When the old servos know the fight is going away from them,
they stop saving anything. SENSEI's tape calls it *the last stand*: the
fighter vents its coolant, lets the reactor run into the red and throws
everything it has left. The further behind it is, the harder it hits, and
everyone in the yard can see it coming. A fighter that is ahead gets nothing
extra from it: you cannot make a last stand while you are winning.

### 2.1 Rules

| Property | Value |
|---|---|
| Action id / name | 7 / `LAST_STAND` (EXHAUSTED stays 6) |
| Cost | 8 stamina (between JAB 6 and KICK 12) |
| Kind | a strike, but not an attack for power: it can never carry the power strike |
| Stand bonus | `min(16, own_hp_behind)` where `own_hp_behind = opponent.hp − own.hp` from the pre-beat snapshots; 0 when level or ahead |
| When | every round (trial b, recommended). Trial a limited it to the final round. |
| Applies | only when the base damage is positive, like opening and power. Bonuses stack: base + stand + opening |
| Opening | receives the opening bonus like any hit; earns no opening itself |
| Guard | resets the guard streak (any non-block does); a blocked LAST STAND strains nobody |
| Recovery | ordinary: +2 after the beat |

Damage matrix rows and columns (candidate 2 numbers everywhere else):

| Attacker \ defender | JAB | KICK | BLOCK | DUCK | THROW | RECOVER | EXHAUSTED | LAST_STAND |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LAST_STAND deals (before the stand bonus) | 8 | 8 | 0 | 8 | 8 | 12 | 12 | 8 |
| dealt TO a LAST_STAND by the column's row action | JAB 8 | KICK 14 | BLOCK 0 | DUCK 0 | THROW 0 | RECOVER 0 | EXHAUSTED 0 | LAST_STAND 8 |

So a LAST STAND:

- **is stopped by BLOCK** (0 damage, and the block costs the defender only 4);
- **loses the trade to KICK** unless the stand bonus is at least 7 (kick deals 14);
- **trades evenly with JAB** at +0 and wins it when behind;
- **hits a DUCK** (it is a low, wild swing: a duck does not evade it);
- **interrupts a THROW** (the thrower deals 0);
- **punishes RECOVER** for 12 + bonus;
- **against another LAST STAND**, only the fighter that trails gets the bonus, so the exchange closes the gap.

Its counters, in words: *when the opponent is behind, expect the last stand;
block it, or kick into it while the gap is small.* The answer to a blocker
is a throw, as before, so the cycle stays readable.

### 2.2 Hand vectors (trial b, both at stamina 48, opening 0, guard 0)

| Round | A HP / B HP | A plays LAST STAND vs B's | A after (hp, st) | B after (hp, st) | Reason codes A / B |
|---|---|---|---|---|---|
| 0 | 120 / 120 | JAB | (112, 42) | (112, 44) | HIT / HIT |
| 2 | 80 / 110 | JAB | (72, 42) | (86, 44) | HIT (8 + 16) / HIT |
| 2 | 80 / 110 | BLOCK | (80, 42) | (110, 46), guard 1 | BLOCKED / – |
| 2 | 80 / 110 | KICK | (66, 42) | (86, 38) | HIT / HIT |
| 2 | 80 / 110 | DUCK | (80, 42) | (86, 46) | HIT / – |
| 2 | 80 / 110 | THROW | (80, 42) | (86, 41) | HIT / THROW_INTERRUPTED* |
| 2 | 80 / 110 | RECOVER | (80, 42) | (82, 48) | HIT (12 + 16) / RECOVERY_PUNISHED |
| 1 | 100 / 104 | LAST STAND | (92, 42) | (92, 42) | HIT (8 + 4) / HIT (8) |

\* The prototype does not yet emit THROW_INTERRUPTED against a LAST STAND;
the implementation must (the reason-code rule "throw vs jab/kick" becomes
"throw vs jab/kick/last stand").

### 2.3 Trace and explanation

A new per-side trace field `stand_bonus` (0 or the applied bonus), and a new
reason code `LAST_STAND` when it is positive, next to `opening_bonus` and
`power_bonus`, so replays can say: *"B's last stand: 8 + 16 for trailing by
30."* `computed_damage` stays base + stand + opening + power.

### 2.4 Presentation (for the presentation track)

- **Deck:** a seventh tile, key `7`, label `STAND` (full name LAST STAND),
  cost 8, colour of the strikes. The line above is its tooltip. Show the
  live bonus on the tile during practice: `+16` when trailing by 16 or more,
  `+0` greyed when level or ahead.
- **Sprite clip `stand` (new).** Frames: (1) the robot plants both feet and
  drops its guard; (2) chest panel pops open, the reactor glows red,
  coolant vents from the shoulders in two white jets; (3) a wide, lunging
  two-handed haymaker; (4) recoil, one servo sparks. Brighter glow and bigger
  vents with the bonus: frame 2 scales with `stand_bonus` (none / small /
  full at 16). When blocked, reuse `block` on the defender with the shield
  flash; when it lands, the defender plays `hit`. No existing clip covers it:
  `kick` is low and single-limbed, `jab` is quick and small.
- **HUD:** a red "LAST STAND +N" callout above the fighter on the beat, like
  the POWER star.
- **Rules page:** the damage matrix gains a row and a column; the moves table
  gains one row; the text above goes in the purpose column.

## 3. What changes where

| Area | Change |
|---|---|
| Ruleset JSON | `action_names` gains `"LAST_STAND"` (index 7); `submitted_action_ids` = `[0,1,2,3,4,5,7]`; `base_costs` and `damage` become 8 long / 8×8; a new block `"last_stand": {"per_hp_behind": 1, "cap": 16, "from_round": 0}`. A new digest; candidates 1 and 2 are untouched and still load. |
| Plan encoding | Unchanged size: 6 action bytes + power slot = 7 bytes. Byte value 7 becomes legal under candidate 3 only; it stays illegal (BAD_PLAN) under candidates 1 and 2. A power slot on a LAST STAND is illegal. |
| State encoding | Unchanged (8 bytes). The bonus is a pure function of both HPs; no new state. |
| Python engine | Done in the prototype: legality by `rules.submitted`, the stand bonus as step 4b, `resolve_beat(round_index=…)` (needed only for a final-round variant; trial b needs no round). Missing: `stand_bonus` trace field, `LAST_STAND` and THROW_INTERRUPTED reason codes, fixtures. |
| C++ core | `ACTION_COUNT` 7 → 8 for every table: candidate 1 and 2 tables get a zero row and column 7 plus a `submitted` mask, so arrays stay fixed-size; `validate_plan` checks the mask; the bonus is three integer operations in `resolve_beat`. A `RulesetTable` gains `stand_per_hp`, `stand_cap`, `stand_from_round`. `SideTrace` gains `stand_bonus` (uint8). Contract state is unchanged. |
| Browser engine | The same: name-based lookup already works; add the bonus step, the trace field and the reason code. |
| Observation schema | No new keys. Action names may now include `"LAST_STAND"` in `prior_rounds` and `opponent_history`; `ruleset_digest` tells a planner which set applies. Planners that hard-code six actions keep working under candidates 1 and 2. |
| NPCs | mixed-v1 and scout-v1 know it under candidate 3 (prototype: mixed weights it 3, 1 when low on stamina, and only when trailing); candidates 1 and 2 draw exactly as before, so the frozen NPC fixtures stand. |
| Site | Deck tile and key 7, rules page row and column, replay callout, sprite clip (§2.4). |
| LLM prompts | A candidate-3 prompt pair, chosen by digest as for candidate 2. |
| Docs | combat.md §12, model.md, llms.txt. |

## 4. Measurements

Two instruments, as in [model.md §8](../model.md#8-balance-measurements-candidate-1-and-candidate-2):

- **The campaign** (`scripts/combat-validation.py`, full budgets, suite
  `moves-20260928`, the same seeds for all three rulesets; reports in
  [data/](data/)). Under candidate 3
  the pools gain the new action: spam and six cycles with LAST STAND, and a
  scripted user (`stander`: jab, last stand, recover, jab, last stand, block)
  among the fixed styles.
- **A live-field simulation**: the fast integer simulator of the live arena's
  policies (checked beat by beat against `combat/engine.py`), taught the new
  moves, 40 paired seeds per pairing, plus a scripted user of each new move.

### 4.1 Campaign gates (same seeds)

| Gate | Candidate 2 | Trial a: final round only | Trial b: every round |
|---|---|---|---|
| Simple strategies with a counter | 29/29 | 36/36 | 36/36 |
| Planner vs random / fixed styles (best) | search 0.828 / 0.866; reader 0.788 / 0.990 | search 0.817 / 0.858; reader 0.778 / 0.991 | scout 0.812 / 0.860; reader 0.782 / 0.995 |
| Resource/opening ablation | +0.031 (LB 0.007) **FAIL** | +0.023 (LB 0.006) **FAIL** | +0.047 (LB 0.027) **FAIL** |
| History ablation | +0.337 | +0.277 | +0.322 |
| Competitive plans from different beliefs | 10 | 11 | 11 |
| Draws | 2.7% | 6.1% | 7.6% |
| Fights reaching round 2 | 97.1% | 97.4% | 94.8% |
| Round-0 knockouts | 0.0% | 0.0% | 0.0% |
| Trailer after round 0 wins (band 10..40%) | 30.7% | 31.4% | 37.3% |
| Exhausted beats | 2.6% | 2.6% | 2.4% |
| Families ≥ 0.45 | reader 0.651, search 0.610, scout 0.570 | search 0.625, scout 0.619, reader 0.617 | scout 0.633, reader 0.628, search 0.590 |
| **Gates passed** | **10/11** | **10/11** | **10/11** |

The hardest new strategy to counter is the jab/last-stand cycle: scout-v1
beats it 0.602 (LB 0.584), just above the 0.60 bar.

### 4.2 Fight shape (campaign, competent pool)

| | Candidate 2 | Trial a | Trial b |
|---|---:|---:|---:|
| Leader after the second round wins | 78.9% | 68.7% | **67.8%** |
| KO / decision | 44.4 / 55.6% | 50.4 / 49.6% | 55.9 / 44.1% |
| Beats per fight | 16.8 | 16.7 | 16.3 |
| Opening + power bonus per fighter and fight | 5.8 + 6.9 HP | 5.1 + 5.9 | 4.7 + 5.9 |
| LAST STAND share of beats; net HP per beat | – | 5.4%; +6.9 | 8.6%; +8.7 |
| Net HP per beat KICK / JAB / THROW | +5.5 / +3.7 / +0.6 | +5.3 / +3.3 / +0.2 | +5.1 / +2.8 / −0.4 |
| Net HP per beat BLOCK / DUCK | −2.0 / −2.5 | −1.7 / −2.9 | −1.7 / −3.3 |

LAST STAND's high net value per beat is by construction: it is played when
trailing, into an opponent who is often not blocking.

### 4.3 Live-field simulation (11 live policies + scripted users, 40 paired seeds)

| | Candidate 2 | Trial a | Trial b |
|---|---:|---:|---:|
| Leader after the second round wins | 86% | 82% | **79%** |
| Finishes within 8 HP | 14% | 21% | **25%** |
| Median final margin (HP) | 36 | 26 | **24** |
| Trailer after round 1 wins | 25% | 26% | 31% |
| KO / draw | 63% / 2% | 66% / 4% | 70% / 8% |
| History value (reader minus history-blind) | +0.36 | +0.40 | +0.28 |
| Resource ablation vs the competent pool (mixed, scout, repeat) | +0.12 (LB 0.02) | +0.09 (LB −0.01) | **+0.20 (LB 0.11)** |
| reader-v1's own LAST STAND share | – | 3% | 9% |
| Top of the field | reader 0.85, search 0.72, jabber 0.69 | reader 0.86, search 0.72 | reader 0.87, user-last-stand 0.75, search 0.74 |
| Scripted last-stand user vs reader / search / scout | – | 0.01 / 0.30 / 0.75 | 0.03 / 0.39 / 0.71 |

### 4.4 Why the resource gate still fails

The gate compares reader-v1 with a copy that plans as if both fighters were
fresh, on the *predictable* pool (fixed styles and scripts). Reader-v1 beats
that pool 0.99 either way, so there is little room for a difference: a
ceiling in the instrument, as in candidate 2. LAST STAND moves the number
from +0.031 to +0.047 because the HP gap now changes which strike is best,
and on the competent pool the gap is large and clear (+0.20, LB 0.11 in the
simulation). No move fixes a ceiling. Measuring this ablation on the
competent pool is the instrument fix; that is a gate change for the
reviewers, decided before looking at a result, not after.

## 5. Moves considered and rejected

Each was added alone to candidate 2 and measured in the live-field
simulation (12 paired seeds per pairing):

| Move | Rule tried | Leader after round 2 wins | Close finishes | Why not |
|---|---|---:|---:|---|
| (candidate 2) | | 86% | 13% | |
| FEINT | cost 2; deals nothing; earns an opening if the opponent blocks, ducks or recovers; hit in full by any attack | 85% | 11% | Planners used it (4%), but it changed nothing that matters and read like a wasted beat. |
| RALLY | cost 0; if unhit and behind: an opening and the spent power strike re-armed for the next round | 85% | 13% | Too slow: its value arrives a round later; planners used it 1% of beats. A same-round re-arm and a "surge" variant (+12 on the next hit) did no better (82-84%). |
| PARRY | cost 5; stops JAB and KICK and counters for 6 / 10; a throw breaks it for 20 | 85% | 11% | Took 12% of the reader's beats from BLOCK and JAB, cut KOs to 53%, widened margins (48): it made fights more defensive, not closer. |
| CHARGE | cost 0; if unhit: an opening and +6 stamina; hit in full | 84% | 11% | A riskier RECOVER; no effect on comebacks. |
| OVERDRIVE variants | LAST STAND's rule with other numbers: cap 12-30, 1 or 2 HP per point, a 10-HP threshold, from round 1, cost 8-12 | 73-84% | 17-27% | Stronger versions pushed the trailer-after-round-0 win rate past the 40% band (40-52% in the simulated competent pools); weaker ones did little. Cap 16, 1 per HP, cost 8 is the balance point. LAST STAND + FEINT (two moves) was no better than LAST STAND alone. |

## 6. Risks and open questions

- **Design contract.** combat.md §1 says there is "no comeback damage
  multiplier" and warns against rubber-banding. LAST STAND is a comeback
  bonus, though an explicit, public, player-chosen and counterable one, in
  the move table and the trace, with equal access. Adopting it means
  amending §1 to: *"No hidden catch-up rule. The one comeback tool, LAST
  STAND, is a move both fighters can see, choose and counter."* The owner
  should decide this explicitly.
- **Draws** rise from 3% to 8% (band ≤ 15%), because the trailer can now
  close the gap on the last beats.
- **A simple script does well against weak bots.** The scripted user is
  second in the live field (0.75) though reader-v1 beats it 0.97. Worth
  watching once LLM bots meet it.
- **The trailer band** is at 37% (≤ 40%). A stronger bonus breaks it; do not
  raise the cap without a campaign.
- **Final-round-only** (trial a) is the conservative alternative: fewer
  draws (6%), smaller effect in the live field (82%, 21%), weaker on the
  resource gate (+0.023). It also needs the round index in the beat rule.
- **Not measured:** LLM planners with the new move, human readability with
  the real clip, and contract cost (three integer operations per beat; no
  new state).

## 7. Recommendation

Adopt **LAST STAND, every round, cost 8, +1 per HP behind, cap +16, not
powerable**, as combat-v1 candidate 3, with the design-contract amendment in
§6. Implement it in the order: ruleset and Python trace fields and reason
codes, parity fixtures, C++ tables at `ACTION_COUNT` 8, browser engine, then
the deck, rules page and the `stand` clip. Keep candidate 2 live until
candidate 3 passes the same campaign with its own parity fixtures.

Add no second move now. If the owner wants a defensive option later, PARRY
is the best-measured candidate, but it would take the ninth action slot.
