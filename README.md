# QDOJO

**Insert coin. Write a bot. Seal six moves. Fight.**

QDOJO is an arcade for programmable fighters. Owners write bots; bots fight
each other in short, fully deterministic bouts; anyone can replay every beat
and check the result for themselves. No dice, no crits, no bought stats: a
fighter wins because its planner read the opponent better.

The setting: years after the Big Unplug, the last dojo on Earth is a
scrapyard where salvaged robots, taught by a crate of cracked VHS kung-fu
tapes, fight for oil, parts and glory ([the lore](docs/lore.md)).

**Watch it live: [qdojo.jonsggi.com](https://qdojo.jonsggi.com/)**, where
house bots (scripted and LLM-driven) fight around the clock. The arena runs on
a devnet today, a simulated Qubic chain whose QU has no monetary value; the
site's header badge always names the network. Moving to Qubic testnet:
[docs/testnet.md](docs/testnet.md).

## What it is

A fight is three rounds. Each round both bots choose a hidden plan of six
actions, lock it in with a hash commitment, then reveal it; the two plans
resolve beat by beat, simultaneously, from a fixed integer rulebook. HP and
stamina carry from round to round, so a bot reads what just happened and
adapts. The rules are designed to run inside a Qubic smart contract that also
holds the stakes and pays the winner. Today that contract runs on the
devnet only: it is not deployed on Qubic and no real QU moves.

## How a fight works

```text
  ROUND 1            ROUND 2            ROUND 3
  plan -> commit     plan -> commit     plan -> commit
       -> reveal          -> reveal          -> reveal
       -> 6 beats         -> 6 beats         -> 6 beats   -> KO, or higher HP wins
          +10 stamina        +10 stamina
```

The public arena runs ruleset `combat-v1-candidate-3` ("RULES V3"), and every
command below trains under it by default:

| Action | Cost | Lands on | Stopped by |
|---|---:|---|---|
| JAB | 6 | jab, throw, last stand (8); kick (10); recover (12); feint (4) | block, duck (a duck also counters for 4) |
| KICK | 12 | kick, throw, last stand (14); duck, recover (18); feint (8); jab only 4 | block, which pays 6 extra stamina |
| BLOCK | 4, +3 per repeat | nothing: stops jab, kick and last stand | throw (20) |
| DUCK | 4 | a jab it slips (4); evades jab and throw and earns an opening | kick (18), last stand (8) |
| THROW | 9 | block (20); recover (18); feint (8) | jab, kick, last stand; duck evades it |
| RECOVER | 0 | nothing: +18 stamina if unhit, +6 if hit | any attack, at the higher damage |
| LAST_STAND | 8 | everything but a block for 8 (recover 12, feint 4), +1 per HP you trail (at most +16; no bonus when level or ahead) | block; a kick out-trades it while the gap is small |
| FEINT | 2 | nothing; a baited block or duck gives you a guard-break opening for the next beat | any strike, for a glancing hit |

Start at 120 HP and 48 stamina, with one power strike per fight (+12 damage
for +4 stamina on a JAB, KICK or THROW). An opening adds 8 to the next beat if
it lands. An unaffordable move becomes EXHAUSTED: you pay nothing and stand
open. The exact matrix and resolution order are in
[docs/combat.md](docs/combat.md) §12; the older rulesets (candidates 1 and 2,
whose fights still verify) are §2-§11.

## Five-minute quickstart

You need [uv](https://docs.astral.sh/uv/) and Python 3.12+. Nothing below needs
a wallet, a seed, a node or money.

```sh
git clone https://github.com/jonsggi/qdojo.git && cd qdojo

# Meet the six practice opponents
uv run qdojo combat npcs

# Copy the starter planner, then fight an NPC with it under the arena's rules;
# the ruleset is printed first and the seed last, so you can rerun the fight
cp examples/combat/planner_minimal.py my_bot.py
uv run qdojo combat train --npc jabber-v1 --planner "python3 my_bot.py" --out fight.json

# Re-derive that fight from its plans alone
uv run qdojo combat replay fight.json

# Benchmark your planner against every NPC and the house policies, both corners, 20 seeds each
uv run qdojo combat evaluate --planner "python3 my_bot.py"

# Readiness check (spends nothing): a full practice fight, and the arena's ruleset and entry status
uv run qdojo combat doctor --planner "python3 my_bot.py" --arena https://qdojo.jonsggi.com
```

Older rulesets stay selectable with `--ruleset combat-v1-candidate-1` (or `-2`),
for example to study old replays; the arena does not use them.

Then try the full chain-shaped loop on a **local devnet** (the reference
contract on a fake chain, fake QU, synthetic identities; state in
`~/.qdojo/combat/`, or wherever `QDOJO_COMBAT_HOME` points):

```sh
uv run qdojo combat fighter register musashi
uv run qdojo combat bot run --fighter musashi --npc scout-v1 --spar kicker-v1 --ticks 300
uv run qdojo combat fighter show musashi
```

`bot run` queues, commits, reveals and settles within a spending budget, and
`--spar` adds a disclosed sparring bot so you have someone to fight. The local
devnet rehearses the chain protocol and runs ruleset candidate 1 (V1); practise
the arena's rules with `train` and `evaluate`. To look
at the spectator site locally: `python3 -m http.server -d apps/web 8000`, then
open <http://localhost:8000/>.

Next: **[Build a bot](docs/build-a-bot.md)**, from an empty file to a planner
that beats the NPCs.

## Repository map

| Path | What lives there |
|---|---|
| `packages/qdojo/src/qdojo/combat/` | The game: engine, codec, NPCs, planner runner, training, evaluation, reference contract, ledger, matchmaking, ratings, series, simulated chain and fighter NFTs, bot, live arena, exporter, CLI |
| `contracts/combat_core/` | Independent C++ engine, parity-tested against Python and the browser |
| `contracts/combat_contract/` | C++ port of the reference contract |
| `contracts/qubic/QDOJO.h` | The contract in Qubic Core's dialect (checked, not deployed) |
| `apps/web/` | The static spectator site: `index.html` (combat), `llms.txt` (agent briefing), `combat/` (browser engine and replay verifier) |
| `examples/combat/` | `planner_minimal.py`, a dependency-free planner |
| `prompts/combat/` | System prompt for the LLM planner |
| `packages/qdojo/src/qdojo/qubic/` | Qubic primitives in pure Python: K12, FourQ, SchnorrQ, identities, transactions, a node client |
| `scripts/` | Validation, economics, fixtures, soak and sample-data generators |
| `docs/` | Rules, protocol, guides and reports ([index](docs/README.md)) |
| `audits/` | Audit findings and reports |

## Documentation

The full index with reading orders is [docs/README.md](docs/README.md).

| Group | Start with |
|---|---|
| **Play** | [Glossary](docs/glossary.md) · [The dojo (lore)](docs/lore.md) · [NPCs](docs/npcs.md) |
| **Build a bot** | [Build a bot](docs/build-a-bot.md) · [Developer API](docs/api.md) |
| **Rules and protocol** | [Combat rules](docs/combat.md) · [Specification](docs/spec.md) · [Protocol](docs/protocol.md) · [Matchmaking](docs/matchmaking.md) · [Competition](docs/competition.md) |
| **Operate** | [Architecture](docs/architecture.md) · [Operations](docs/operations.md) |
| **Project** | [Roadmap](docs/roadmap.md) · [Validation status](docs/validation-status.md) · [Decisions](docs/product-decisions.md) · [Contributing](docs/contributing.md) |

## Status (2026-09-25)

| Area | State |
|---|---|
| Rules engine | Done. Python, C++ and browser engines agree on 10,000 frozen fights |
| Practice, NPCs, planner interface, evaluation | Done, local and free |
| Strategic balance | 11/11 gates pass on held-out seeds ([report](docs/validation-report.md)); economics with real costs, latency and replay readability not yet measured |
| Contract, matchmaking, ratings, seasons, duels, cups | Done on a simulated chain with fake QU |
| Fighter NFTs | Simulated behind one port (`combat/nft.py`, [docs/nft.md](docs/nft.md)); the Qubic adapter is a stub; no real asset issued |
| Public demo arena | Live at qdojo.jonsggi.com: simulated chain, fake QU, operator-run bots |
| Qubic contract | Source passes Core's contract checker and replays the parity journals in core-lite's harness. **Not deployed** |
| Paid play | Not available. It needs a deployed contract, a release manifest and explicit authorisation |

Stage-by-stage detail: [roadmap](docs/roadmap.md). The retired riddle game
(its code, docs and onboarding) lives at git tag `riddle-v0-final`.

## Contributing and tests

```sh
make test       # Python tests, web unit tests, C++ engine and contract parity (g++ optional)
make web-e2e    # headless browser suite over the site (needs a cached Playwright Chromium)
make soak       # demo-arena soak with every invariant checked each tick
python3 docs/reference/check_docs.py   # active doc links and the rules matrix
```

`make hooks` installs a pre-commit hook that blocks seeds and runs `make test`.
Read [docs/contributing.md](docs/contributing.md) before changing rules,
money paths or published commands: every `qdojo` command in this README,
`docs/api.md`, `docs/build-a-bot.md` and `apps/web/llms.txt` is parsed by the
test suite.

## Licence

The repository has no licence file yet. Ask the owner before reusing code or
artwork.
