# Build a bot

> **Purpose:** the fastest path from an empty file to a planner that beats the practice NPCs, and what changes when real registration exists. \
> **Audience:** bot builders (human or coding agent). \
> **Status:** guide. The binding interface is [api.md](api.md) §1; the rules are [combat.md](combat.md). \
> **Last verified:** 2026-09-25. Every command here was run from a clean checkout with `uv`.

## Contents

1. [Ready, fight](#1-ready-fight)
2. [The planner contract](#2-the-planner-contract)
3. [What your planner sees](#3-what-your-planner-sees)
4. [Train against every NPC](#4-train-against-every-npc)
5. [Strategy notes from the rules](#5-strategy-notes-from-the-rules)
6. [On the local devnet](#6-on-the-local-devnet)
7. [LLM planners](#7-llm-planners)
8. [Later: real registration](#8-later-real-registration)

## 1. Ready, fight

You need `uv`, Python 3.12+ and a checkout of this repository. No wallet,
seed, node or NFT is involved anywhere in this guide.

```sh
cp examples/combat/planner_minimal.py my_bot.py
uv run qdojo combat train --npc jabber-v1 --planner "python3 my_bot.py"
```

You get a beat-by-beat table, the result, the seed (rerun with `--seed` to get
the identical fight), and a "Where it cost you" list: each beat where you lost
HP, with what a different action would have done against the opponent's
*recorded* move. That is hindsight, not a promise the opponent would have
played the same way.

Prefer clicking first? The site's PRACTICE screen
([qdojo.jonsggi.com/#practice](https://qdojo.jonsggi.com/#practice), or your
local copy) lets you play the same NPCs by hand with the same engine.

## 2. The planner contract

A planner is any program. Once per round the bot runs it, writes **one JSON
object** to its stdin and closes stdin. The planner prints **exactly one JSON
object** to stdout and exits 0. Diagnostics go to stderr.

The smallest legal planner:

```python
#!/usr/bin/env python3
import json, sys

obs = json.load(sys.stdin)                      # qdojo.combat.observation.v1
# power the KICK at index 2, once, in the last round
power = 2 if obs["round_index"] == 2 and obs["self"]["power_available"] else -1
print(json.dumps({
    "schema": "qdojo.combat.plan.v1",
    "actions": ["DUCK", "DUCK", "KICK", "DUCK", "THROW", "RECOVER"],
    "power_slot": power,
}))
```

Rules the runner enforces (`combat/planner.py`):

- `actions`: exactly six of `JAB KICK BLOCK DUCK THROW RECOVER`, uppercase.
- `power_slot`: `-1`, or the index of a `JAB`, `KICK` or `THROW` while you still
  have the power strike. It is once per fight.
- Exactly the keys `schema`, `actions`, `power_slot`. Unknown keys, floats,
  booleans for the slot, extra output, a nonzero exit, more than 4096 bytes of
  stdout, or missing the time budget (default 1500 ms, `--budget-ms`) all fail.
- A failed planner does not stall the fight: the round is played with the
  fallback plan, six `RECOVER`s, and the CLI says so. That usually loses.
- Your planner never receives a salt, a key or the opponent's live plan, and
  its output is never passed to a shell.

`uv run qdojo combat doctor --planner "python3 my_bot.py"` feeds it a sample
observation and reports PASS or FAIL without spending anything.

## 3. What your planner sees

Everything is in the observation. In local practice it looks like this
(abridged; captured from a real round-2 call):

```json
{
  "schema": "qdojo.combat.observation.v1",
  "mode": "practice",
  "fight_id": "1", "round_index": 1, "self_slot": "B",
  "self":     {"fighter_id": "6e3c…", "hp": 100, "stamina": 59, "opening": 0, "guard_streak": 0, "power_available": false},
  "opponent": {"fighter_id": "551b…", "hp": 60,  "stamina": 60, "opening": 0, "guard_streak": 0, "power_available": true},
  "deadlines": null, "observed_tick": null,
  "prior_rounds": [ { "round_index": 0, "plans": {…}, "beats": […], "break_recovery": {"A": 0, "B": 10}, "end": {…}, "unexecuted": {"A": [], "B": []} } ],
  "history_manifest": {"opponent_fight_ids": [], "as_of_tick": null},
  "decision_budget_ms": 1500
}
```

| Field | Use it for |
|---|---|
| `round_index` | 0, 1 or 2. Round 2 is the last: HP decides if nobody is knocked out |
| `self_slot` | `"A"` or `"B"`: which side of each beat record is you |
| `self`, `opponent` | Round-start HP, stamina, opening, guard streak and power, after the break recovery |
| `prior_rounds` | Every earlier round of **this fight**: both revealed plans, and per beat for each side `intended`, `effective` (`EXHAUSTED` if unaffordable), `power`, `cost_paid`, `computed_damage`, `actual_hp_lost`, `strain`, `recovered`, `reasons`, plus `before`/`after` states |
| `unexecuted` | Actions revealed but never played because of a knockout. Do not count them as the opponent's habits |
| `deadlines`, `observed_tick` | Tick deadlines on a chain; `null` in local practice |
| `history_manifest` | Meant to list the opponent's earlier public fights. **Not built yet: always empty.** Today a planner only learns from the current fight |
| `decision_budget_ms` | Your time budget |

Note that `self`/`opponent` give `power_available` as a boolean, while the
`before`/`after` states inside beat records use `0`/`1`.

## 4. Train against every NPC

The six NPCs are disclosed policies with the same stats as you
(`uv run qdojo combat npcs`; full behaviour in [npcs.md](npcs.md)):

| NPC | Plays | A plan that beats it (verified, seed `00…03`) |
|---|---|---|
| `random-v1` | Uniform random actions, random power; exhausts itself | Anything disciplined about stamina |
| `jabber-v1` | `JAB JAB JAB RECOVER JAB JAB` every round | `DUCK KICK DUCK KICK DUCK KICK`: KO in round 3 |
| `turtle-v1` | `BLOCK BLOCK RECOVER BLOCK DUCK RECOVER` | `THROW THROW THROW THROW KICK THROW`: KO in round 2, no HP lost |
| `kicker-v1` | `KICK RECOVER KICK RECOVER KICK RECOVER` | `BLOCK THROW BLOCK THROW BLOCK THROW`: KO in round 3 |
| `mixed-v1` | Weighted random, stamina-aware | Needs real reading of the fight |
| `scout-v1` | Counters the action mix you showed in earlier rounds | Needs you to change between rounds |

The fixed-pattern NPCs power their first attack in the last round.

One fight per NPC with a fixed seed:

```sh
uv run qdojo combat train --npc turtle-v1 --planner "python3 my_bot.py" --seed 0000000000000000000000000000000000000000000000000000000000000003
```

Add `--out fight.json` to save the replay, and `uv run qdojo combat replay fight.json`
to re-derive it from the plans alone. `--json` prints everything machine-readably.

**Many fights.** `qdojo combat evaluate` benchmarks only the built-in
policies, not a planner command. For your own planner, a short script using the
library does the same job. Save as `bench.py` in the repository root:

```python
# bench.py: your planner against every NPC on 20 fixed seeds each
import hashlib, sys
from qdojo.combat import npcs
from qdojo.combat.training import Contestant, run_fight

planner = sys.argv[1:] or ["python3", "my_bot.py"]
for npc in npcs.ROSTER:
    w = d = l = 0
    for i in range(20):
        seed = hashlib.sha256(f"bench/{npc}/{i}".encode()).digest()
        replay = run_fight(Contestant("you", command=planner), Contestant(npc, npc=npc), seed)
        winner = replay["outcome"]["winner"]
        mine = "A" if replay["fighters"]["A"]["name"] == "you" else "B"
        if winner is None: d += 1
        elif winner == mine: w += 1
        else: l += 1
    print(f"{npc:<10} W{w:>3} D{d:>3} L{l:>3}")
```

```sh
uv run python bench.py python3 my_bot.py
```

The unmodified example planner scores roughly: random 15-1-4, jabber 20-0-0,
turtle 20-0-0, kicker 0-20-0 (all double knockouts), mixed 13-0-7, scout 3-1-16.
Beating `scout-v1` consistently is the first real milestone. Keep a separate set
of seeds you never tune on, so the score you report is honest.

To see how strong play looks, the research policies can be benchmarked
directly: `uv run qdojo combat evaluate --policy reader-v1 --seeds 20`
(also `search-v1`, `scout-v1`, `mixed-v1`; pools with `--pool`). The
[validation report](validation-report.md) has their full numbers.

## 5. Strategy notes from the rules

All numbers are from [combat.md](combat.md). Start: 100 HP, 60 stamina (the cap).

**Stamina is the clock.** Every executed action except `RECOVER` refunds 2, so
the net cost per beat is `JAB` 4, `KICK` 10, `DUCK` 2, `THROW` 7, `BLOCK` 2
then 5, 8, 11 while you keep blocking. Six kicks from 60 stamina leave you
exhausted on beat 6. The break between rounds gives only +10.

**Exhaustion is expensive.** An unaffordable move becomes `EXHAUSTED`: no
cost, no damage dealt, full damage taken (a jab does 12, a kick or throw 18),
+6 stamina. The plan is fixed for all six beats, so budget before you commit.

**`RECOVER` is a bet.** +18 stamina if nothing hits you, +6 if something does,
and every attack does its highest damage against it.

**Openings compound.** Ducking a jab or throw, or landing a jab while taking
nothing, gives +4 damage on the very next beat if that beat lands. `DUCK`
then `KICK` into a predictable jabber is 18 damage per pair.

**Blocks decay.** Consecutive blocks cost 4, 7, 10, then 13. A `THROW` breaks
a block for 14; a `KICK` into a block does no HP damage but costs the blocker 6
extra stamina.

**Power is once per fight.** +4 damage for +4 stamina on a `JAB`, `KICK` or
`THROW`. It is spent even if the move is blocked, evaded or exhausted, and it
never turns a zero into damage. Save it for a beat you are confident lands.

**Know how fights end.** Zero HP is a knockout; both at zero on the same beat
is a draw. After round 3 the higher HP wins and equal HP is a draw. A lead
going into round 3 can be protected.

**Be hard to read.** `scout-v1` counts the actions you executed in earlier
rounds and answers the most useful counter. Anyone who studies your replays
can do the same, and every fight is public.

## 6. On the local devnet

The devnet runs the reference contract on a fake chain with fake QU and
synthetic identities derived from labels. State lives in
`~/.qdojo/combat/devnet` (set `QDOJO_COMBAT_HOME` to move it).

```sh
uv run qdojo combat fighter register musashi
uv run qdojo combat bot run --fighter musashi --npc scout-v1 --spar kicker-v1 --ticks 300
uv run qdojo combat fighter show musashi
```

`bot run` enters the ranked queue, commits, reveals and settles within a
budget (`--budget` takes a JSON file of the `Budget` fields in
`combat/bot.py`), and journals each plan and salt (mode 0600) before
committing. `--spar` adds a disclosed sparring bot so you have an opponent.

**Known issue (2026-09-25):** `bot run --planner "…"` currently forfeits its
first fight on the devnet. The CLI advances ticks without waiting for the
planner subprocess, which runs in the background, so the commit window closes
first; the default budget then stops the bot after one fault. Use `--npc` with
a built-in policy on the devnet for now, and `train` for your own planner.

## 7. LLM planners

`qdojo.combat.llm_planner` is a planner that asks a model on OpenRouter for the
plan, using [the system prompt](../prompts/combat/planner-system.md). It checks
the answer like any plan, caps spend per UTC day, and falls back to the local
`mixed-v1` policy on any failure or when the cap is reached. It reads the key
from `OPEN_ROUTER_API_KEY` in the environment, never from the command line.

```sh
uv run qdojo combat train --npc jabber-v1 --budget-ms 25000 --planner "uv run python -m qdojo.combat.llm_planner --model some/model --state .llm-state --daily-usd 0.50"
```

Model calls take seconds, so raise `--budget-ms` above the planner's own
`--timeout` (20 s by default). Several fighters in the live demo arena are
LLM-driven.

## 8. Later: real registration

Not available today. When it is, the path will be:

1. A fighter is a recognized one-unit Qubic asset (NFT). Registration binds
   it to the contract; the owner then authorizes an operator key for the bot.
2. The bot enters funded offers (ranked, named duels, cups) with real QU,
   within the owner's budget.
3. Commit/reveal deadlines are chain ticks. A missed reveal forfeits the whole
   contest; a slow planner gets no extra time.

None of this exists yet: there is no deployed contract, no issued fighter
asset and no release manifest. The rules for ownership, operators and money
are already specified in [spec.md](spec.md) §4–5 and [protocol.md](protocol.md);
open launch values are in [product-decisions.md](product-decisions.md).
Nothing in this repository asks for your seed, and nothing should.
