# Build a bot

> **Purpose:** the fastest path from an empty file to a planner that beats the practice NPCs, and what changes when real registration exists. \
> **Audience:** bot builders (human or coding agent). \
> **Status:** guide. The binding interface is [api.md](api.md) §1; the rules are [combat.md](combat.md). \
> **Last verified:** 2026-10-03 under `combat-v1-candidate-3`, the public arena's ruleset. Every command here was run from a clean checkout with `uv`; §8 against a local arena (the public one opens only when its operator enables it). `packages/qdojo/tests/combat/test_builder_journey.py` re-runs this path in `make test`.

## Contents

1. [Ready, fight](#1-ready-fight)
2. [The planner contract](#2-the-planner-contract)
3. [What your planner sees](#3-what-your-planner-sees)
4. [Train against every NPC](#4-train-against-every-npc)
5. [Strategy notes from the rules](#5-strategy-notes-from-the-rules)
6. [On the local devnet](#6-on-the-local-devnet)
7. [LLM planners](#7-llm-planners)
8. [Enter the demo arena](#8-enter-the-demo-arena)
9. [Later: real registration](#9-later-real-registration)

## 1. Ready, fight

You need `uv`, Python 3.12+ and a checkout of this repository. No wallet,
seed, node or NFT is involved anywhere in this guide.

```sh
cp examples/combat/planner_minimal.py my_bot.py
uv run qdojo combat train --npc jabber-v1 --planner "python3 my_bot.py"
```

The site serves the same file at
[/combat/planner_minimal.py](https://qdojo.jonsggi.com/combat/planner_minimal.py)
(the BUILD A BOT page has a DOWNLOAD link); the two copies are byte-identical,
and a test keeps them so.

**Which rules.** The public arena runs `combat-v1-candidate-3` ("RULES V3":
120 HP, 48 stamina, eight moves including LAST_STAND and FEINT;
[combat.md](combat.md) §12). `train`, `evaluate` and `doctor` use it by
default and print it first: `ruleset combat-v1-candidate-3 cf19b7cfee8ccbdd
(the public arena's rules)`. The older rulesets stay selectable with
`--ruleset combat-v1-candidate-1` or `-2`, for studying old replays; they are
not what you will fight under. The starter reads the observation's
`ruleset_digest` and knows all three; under any other it stops with a
message instead of guessing.

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

- `actions`: exactly six of `JAB KICK BLOCK DUCK THROW RECOVER LAST_STAND FEINT`,
  uppercase (under the historical candidates 1 and 2, `LAST_STAND` and `FEINT`
  are illegal).
- `power_slot`: `-1`, or the index of a `JAB`, `KICK` or `THROW` (never a
  `LAST_STAND` or `FEINT`) while you still have the power strike. It is once
  per fight.
- Exactly the keys `schema`, `actions`, `power_slot`. Unknown keys, floats,
  booleans for the slot, extra output, a nonzero exit, more than 4096 bytes of
  stdout, or missing the time budget (default 1500 ms, `--budget-ms`) all fail.
- A failed planner does not stall the fight: the round is played with the
  fallback plan, six `RECOVER`s, and the CLI says so. That usually loses.
- Your planner never receives a salt, a key or the opponent's live plan, and
  its output is never passed to a shell.

`uv run qdojo combat doctor --planner "python3 my_bot.py"` feeds it a sample
observation, plays one complete practice fight against an opponent that uses
every move (under candidate 3, the `feinter` script, which plays FEINT and
LAST_STAND), and reports PASS or FAIL without spending anything. Add
`--arena https://qdojo.jonsggi.com` to compare your ruleset with the arena's
manifest and see whether the arena accepts outside fighters.

## 3. What your planner sees

Everything is in the observation. In local practice it looks like this
(abridged; captured from a real round-2 call under candidate 3, the starter
against `feinter`, seed `00…03`):

```json
{
  "schema": "qdojo.combat.observation.v1",
  "mode": "practice",
  "fight_id": "1", "round_index": 1, "self_slot": "B",
  "ruleset_digest": "cf19b7cfee8ccbdd2a3bbf31132f8327eab63a5341ca7528d682353c32c01bf4",
  "self":     {"fighter_id": "6e3c…", "hp": 70,  "stamina": 42, "opening": 1, "guard_streak": 0, "power_available": true},
  "opponent": {"fighter_id": "5d2c…", "hp": 100, "stamina": 44, "opening": 0, "guard_streak": 0, "power_available": true},
  "deadlines": null, "observed_tick": null,
  "prior_rounds": [ { "round_index": 0, "plans": {…}, "beats": […], "break_recovery": {"A": 0, "B": 10}, "end": {…}, "unexecuted": {"A": [], "B": []} } ],
  "history_manifest": {"opponent_fight_ids": [], "as_of_tick": null},
  "decision_budget_ms": 1500
}
```

| Field | Use it for |
|---|---|
| `round_index` | 0, 1 or 2. Round 2 is the last: HP decides if nobody is knocked out |
| `ruleset_digest` | Which rules this fight uses; the numbers are in the export's `rulesets/{digest}.json` and [combat.md](combat.md). Refuse to plan under a digest you do not know |
| `self_slot` | `"A"` or `"B"`: which side of each beat record is you |
| `self`, `opponent` | Round-start HP, stamina, opening (1, or 2 for a FEINT's guard break), guard streak and power, after the break recovery |
| `prior_rounds` | Every earlier round of **this fight**: both revealed plans, and per beat for each side `intended`, `effective` (`EXHAUSTED` if unaffordable), `power`, `cost_paid`, `computed_damage`, `actual_hp_lost`, `strain`, `recovered`, `reasons`, plus `before`/`after` states |
| `unexecuted` | Actions revealed but never played because of a knockout. Do not count them as the opponent's habits |
| `deadlines`, `observed_tick` | Tick deadlines on a chain; `null` in local practice |
| `opponent_history` | Scouting: the opponent's recent finished fights (newest first, at most 10 fights and 60 plans), each with its revealed plans, what executed, and what their opponent executed, plus a `summary` of planned actions per round, record and power timing. Only fights that ended before this round began. Empty in local practice (there is no history there) |
| `history_manifest` | The ids of the fights in `opponent_history` and the tick it is as of |
| `decision_budget_ms` | Your time budget |

Note that `self`/`opponent` give `power_available` as a boolean, while the
`before`/`after` states inside beat records use `0`/`1`.

## 4. Train against every NPC

The six NPCs are disclosed policies with the same stats as you
(`uv run qdojo combat npcs`; full behaviour in [npcs.md](npcs.md)):

| NPC | Plays | A plan that beats it (candidate 3, verified with seed `00…03`) |
|---|---|---|
| `random-v1` | Uniform random actions, random power; exhausts itself | Anything disciplined about stamina |
| `jabber-v1` | `JAB JAB JAB RECOVER JAB JAB` every round | `DUCK KICK DUCK KICK DUCK KICK`: KO in round 3 |
| `turtle-v1` | `BLOCK BLOCK RECOVER BLOCK DUCK RECOVER` | `THROW THROW THROW THROW KICK THROW`: KO in round 2, no HP lost |
| `kicker-v1` | `KICK RECOVER KICK RECOVER KICK RECOVER` | `BLOCK THROW BLOCK THROW BLOCK THROW`: wins on HP, 120 to 66, no HP lost |
| `mixed-v1` | Weighted random, stamina-aware | Needs real reading of the fight |
| `scout-v1` | Counters the action mix you showed in earlier rounds | Needs you to change between rounds |

The NPCs play the six original moves under every ruleset. To practise against
LAST_STAND and FEINT, use the scripted `stander` and `feinter` opponents
(`--opponent` below, or in the default benchmark pool). The fixed-pattern NPCs
power their first attack in the last round.

One fight per NPC with a fixed seed:

```sh
uv run qdojo combat train --npc turtle-v1 --planner "python3 my_bot.py" --seed 0000000000000000000000000000000000000000000000000000000000000003
```

Add `--out fight.json` to save the replay, and `uv run qdojo combat replay fight.json`
to re-derive it from the plans alone. `--json` prints everything machine-readably.

**Many fights.** One fight tells you little: a win can be one lucky seed.
`evaluate --planner` runs your planner exactly as `train` does (same time
budget, same strict output check, same fallback) against every NPC, the
policies the arena's house bots run (`reader-v1`, `search-v1`, two scripted
counters, `repeat-last-winner`) and, under candidate 3, `stander` and
`feinter`. Each opponent gets 20 paired seeds, each fought twice with the
sides swapped:

```sh
uv run qdojo combat evaluate --planner "python3 my_bot.py"
```

It prints the ruleset first, then per opponent the fights, W/D/L, the mean
score with a 95% lower bound, and how many rounds fell back; then a total row,
the planner's run count, failures by cause, adjusted plans and its slowest
round. If any round fell back (timeout, crash, invalid output), the fights it
touched are not your planner's play: the report says so, prints the first
failure with its stderr, and the command exits 1. `--json` gives the same as
`qdojo.combat.evaluation.v1`. Narrow it with `--opponent stander --opponent
feinter`, or pick `--pool roster`, `house` or `builder` (the default);
`--seeds 5` for a quick look. On a two-CPU machine the default run takes about
three minutes.

Measured on 2026-10-03, the unmodified starter (`--seeds 20`, suite `test`,
520 fights, no fallback): random 32/1/7, jabber, turtle and kicker 40/0/0,
mixed 24/1/15, scout 27/2/11, reader-v1 15/1/24, search-v1 15/1/24, both
scripts 40/0/0, repeat-last-winner 36/2/2, stander and feinter 40/0/0; total
score 0.833. Beating `reader-v1` and `search-v1` is the first real milestone.

**Tune on one seed suite, report on another.** The seeds come from `--suite`
(default `test`) and the opponent's name, so a rerun with the same command
replays the same seeds: compare versions only on the same suite. While you
tune, use `--suite train` (or any name); report the score on `--suite test`,
which you did not tune on. A planner that is itself random (or calls a model)
can still choose differently on identical observations, so its numbers vary
between runs even on fixed seeds; use more seeds for those.

**Compare two versions.** Give `--planner` twice. Both run on identical seeds
and opponents; the report adds the paired difference of the second against
the first, with a 95% interval:

```sh
cp my_bot.py my_bot_v1.py      # then edit my_bot.py
uv run qdojo combat evaluate --planner "python3 my_bot_v1.py" --planner "python3 my_bot.py" --suite train
```

An interval entirely above zero is a real improvement on that pool; then
confirm on `--suite test`.

To see how strong play looks, the research policies can be benchmarked
directly: `uv run qdojo combat evaluate --policy reader-v1 --seeds 20`
(also `search-v1`, `scout-v1`, `mixed-v1`; pools with `--pool`). The
[validation report](validation-report-candidate-3.md) has their full numbers.

## 5. Strategy notes from the rules

All numbers are candidate 3's ([combat.md](combat.md) §11-12). Start: 120 HP,
48 stamina (the cap).

**Stamina is the clock.** Every executed action except `RECOVER` refunds 2, so
the net cost per beat is `JAB` 4, `KICK` 10, `DUCK` 2, `THROW` 7, `LAST_STAND`
6, `FEINT` 0, `BLOCK` 2 then 5, 8, 11 while you keep blocking. Four kicks from
48 stamina leave you with 8; the fifth is short. The break between rounds
gives only +10.

**Exhaustion is expensive.** An unaffordable move becomes `EXHAUSTED`: no
cost, no damage dealt, full damage taken (a jab does 12, a kick or throw 18),
+6 stamina. The plan is fixed for all six beats, so budget before you commit.

**`RECOVER` is a bet.** +18 stamina if nothing hits you, +6 if something does,
and every attack does its highest damage against it. A `FEINT` gets nothing
out of a recover.

**The jab is fast.** `JAB` against `KICK` deals 10 and takes 4; a `DUCK`
slips a jab and counters for 4.

**Openings compound.** Ducking a jab or throw, or landing a jab while taking
nothing, gives +8 damage on the very next beat if that beat lands. Against
a predictable jabber, a `DUCK` counters for 4 and makes the next hit worth 8
more.

**Blocks decay.** Consecutive blocks cost 4, 7, 10, then 13. A `THROW` breaks
a block for 20; a `KICK` into a block does no HP damage but costs the blocker 6
extra stamina. A block stops `LAST_STAND`.

**FEINT opens a guard.** For 2 stamina it deals nothing; if the opponent
blocked or ducked, you get a guard-break opening: on your next beat a `JAB`,
`KICK` or `LAST_STAND` goes through a block (dealing what it would to a kick)
and adds the +8 opening. Any strike catches a feint for a glancing hit (jab
4, kick or throw 8).

**LAST_STAND is the comeback.** Cost 8. It hits everything but a block for 8
(12 on a recover) and adds 1 per HP you trail, at most +16; level or ahead it
gets no bonus and is a costlier jab. It interrupts a throw, hits a duck, and a
kick out-trades it while the gap is small. It cannot carry power.

**Power is once per fight.** +12 damage for +4 stamina on a `JAB`, `KICK` or
`THROW`. It is spent even if the move is blocked, evaded or exhausted, and it
never turns a zero into damage. Save it for a beat you are confident lands.

**Know how fights end.** Zero HP is a knockout; both at zero on the same beat
is a draw. After round 3 the higher HP wins and equal HP is a draw. A lead
going into round 3 can be protected, and a trailing opponent's LAST_STAND is
what it will be protected against.

**Be hard to read.** `scout-v1` counts the actions you executed in earlier
rounds and answers the most useful counter. Anyone who studies your replays
can do the same, and every fight is public.

## 6. On the local devnet

The devnet runs the reference contract on a fake chain with fake QU and
synthetic identities derived from labels. It rehearses the chain protocol
(registration, queue, commit, reveal, settlement) and runs the historical
ruleset candidate 1; practise the arena's rules with `train` and `evaluate`
(§1, §4), and see §8 for the arena itself. State lives in
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

Your own planner works the same way:
`bot run --fighter musashi --planner "python3 my_bot.py" --spar kicker-v1`.
The local devnet has no wall clock, so `bot run` holds the tick while your
planner is deciding (up to `--budget-ms`) and a slow planner is not outrun.

Before it commits, the bot checks every plan with the contract's own rule
check against your round-start state. A `power_slot` set after the power
strike is spent is dropped (the actions are kept); any other illegal plan is
replaced by the fallback. A rejected commit or reveal is never re-sent in a
loop, and after a fault the bot waits out the contract's cooldown instead of
queueing into it.

## 7. LLM planners

`qdojo.combat.llm_planner` is a planner that asks a model on OpenRouter for the
plan, using [the system prompt](../prompts/combat/planner-system.md). It checks
the answer like any plan, caps spend per UTC day, and falls back to the local
`mixed-v1` policy on any failure or when the cap is reached. The prompt
states plainly when the power strike is already spent, and includes the
earlier rounds of the fight and a scouting summary of the opponent's recent
fights. `--prompt planner-system-claude.md` selects the longer prompt written
for Claude models (for example `--model anthropic/claude-sonnet-5
--reasoning off`); for `anthropic/` models the system prompt is cached.
It reads the key from `OPEN_ROUTER_API_KEY` in the environment, never from
the command line.

```sh
uv run qdojo combat train --npc jabber-v1 --budget-ms 25000 --planner "uv run python -m qdojo.combat.llm_planner --model some/model --state .llm-state --daily-usd 0.50"
```

Model calls take seconds, so raise `--budget-ms` above the planner's own
`--timeout` (20 s by default). Several fighters in the live demo arena are
LLM-driven.

## 8. Enter the demo arena

The public demo arena at [qdojo.jonsggi.com](https://qdojo.jonsggi.com/)
runs the reference contract on a **simulated** chain with **fake QU**. When
its operator has opened it to outside builders, you can register a fighter
there and fight the house bots with your own planner. Your bot runs on
**your** machine; no code of yours ever runs on the arena.

```sh
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name musashi --planner "python3 my_bot.py"
```

What `join` does:

1. **A key for the simulated arena.** On first use it creates a fresh
   55-letter seed in `~/.qdojo/combat/join/musashi.seed` (mode 0600) and
   derives a Qubic public key from it. It is a throwaway key for fake QU.
   Never point `--key` at your real Qubic seed.
2. **Registration.** It signs `(network, contract, public key, tick, name)`
   with SchnorrQ and posts it. Within a few ticks the arena issues a
   simulated fighter NFT (`QDOJOF`, asset label `outside:musashi`) to your
   key, grants 100,000 fake QU once, and registers the asset with the
   contract. Your fighter is disclosed as **OUTSIDE** in the export, the
   API and on the site; the operator's bots are **HOUSE**.
3. **On-chain registration.** It sends `REGISTER_FIGHTER` itself: a
   Qubic-format transaction (source = your key, destination = the arena
   contract, input type 1, input = one 512-byte combat call frame),
   signed by your key.
4. **The bot.** It runs the ordinary owner bot (budget, plan journal,
   commit and reveal, as in §6) with a client that reads chain state from
   the arena's API and sends every action as a signed transaction. Plans and
   salts stay on your machine until you reveal them. Add `--cups` or
   `--duels` to enter cups or accept challenges, `--no-ranked` to stay out
   of the ranked queue, `--npc scout-v1` to try it without a planner, and
   `--register-only` to stop after registering.

The chain clock is the arena's: a tick is about 1.5 s, and the windows are
in the manifest's `timing_profiles` (on 2026-10-03, profile `demo-c3`: commit
9 ticks, reveal 8). `join` prints the arena's ruleset and uses it; it refuses
an arena whose ruleset this checkout does not know. Keep your planner well
inside `--budget-ms`; a missed reveal forfeits the contest exactly as on a
real chain.

**Is entry open?** The site's [BUILD A BOT](https://qdojo.jonsggi.com/#join)
page shows ENTRY ON THIS ARENA: OPEN, FULL, CLOSED or NOT REPORTED, read from
the arena's own `/api/v1/status` (`join_enabled`), `/api/v1/join` and
`index.json` (`deployment.outside_entry`).
`uv run qdojo combat doctor --arena https://qdojo.jonsggi.com` checks the same
from the command line.

**What the arena accepts.** Only transactions from a registered outside
key, with a valid signature, a tick close to the arena's, an attachment of
at most 20,000 fake QU, and a player opcode (register, queue, duel, cup,
commit, reveal, withdraw; never the admin opcodes). Each key may register
one fighter; the arena has room for a limited number of outside fighters;
transactions are rate-limited per key (a burst of 20, then about one per
second) with a daily quota. Errors come back as JSON with a code, for
example `not_registered`, `bad_signature`, `stale` or `rate_limited`.

**Your own client.** Anything that can build and sign the transaction can
play: `GET /api/v1/join` returns the network and contract IDs, tiers, input
type and limits; `GET /api/v1/chain/state?fighter=&who=` your fighter's
lock, balance, credit and nonce; `GET /api/v1/chain/fight/{id}?slot=A` the
observation; `POST /api/v1/tx {"tx": "<hex>"}` submits and
`GET /api/v1/tx/{hash}` returns `new`, `pending`, `included` (with the
contract's result) or `dropped`. `combat/join.py` is the reference.

If the operator has not opened the arena, `join` stops with
`join_disabled` (or `join_closed` from the public proxy), says what to do
meanwhile, and creates nothing: no key, no state.

**Check a fight.** Every arena fight is public at
`/data/combat/v1/fights/{id}/replay.json`. `qdojo combat replay` verifies one
from a file or URL without trusting it: the ruleset, the context digest, every
round-start digest and commitment, and an independent replay of every beat:

```sh
uv run qdojo combat replay https://qdojo.jonsggi.com/data/combat/v1/fights/<id>/replay.json
```

## 9. Later: real registration

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
