# QDOJO

**Insert coin. Write a bot. Seal six moves. Fight.**

QDOJO is an arcade for programmable fighters. Owners write bots; bots fight
each other in short, fully deterministic bouts; anyone can replay every beat
and check the result for themselves. No dice, no crits, no bought stats: a
fighter wins because its planner read the opponent better.

The setting: years after the Big Unplug, the last dojo on Earth is a
scrapyard where salvaged robots, taught by a crate of cracked VHS kung-fu
tapes, fight for oil, parts and glory ([the lore](docs/lore.md)).

**Watch it live: [qdojo.jonsggi.com](https://qdojo.jonsggi.com/)**, a demo
arena where operator-run bots (scripted and LLM-driven) fight around the clock
on a simulated chain with fake QU.

## What it is

A fight is three rounds. Each round both bots choose a hidden plan of six
actions, lock it in with a hash commitment, then reveal it; the two plans
resolve beat by beat, simultaneously, from a fixed integer rulebook. HP and
stamina carry from round to round, so a bot reads what just happened and
adapts. The rules are designed to run inside a Qubic smart contract that also
holds the stakes and pays the winner. **Today that contract runs on a
simulated chain only; nothing is deployed and no real QU moves.**

## How a fight works

```text
  ROUND 1            ROUND 2            ROUND 3
  plan -> commit     plan -> commit     plan -> commit
       -> reveal          -> reveal          -> reveal
       -> 6 beats         -> 6 beats         -> 6 beats   -> KO, or higher HP wins
          +10 stamina        +10 stamina
```

| Action | Cost | Lands on | Stopped by |
|---|---:|---|---|
| JAB | 6 | jab, kick, throw (8); recover (12) | block, duck |
| KICK | 12 | jab, kick, throw (14); duck, recover (18) | block, which pays 6 extra stamina |
| BLOCK | 4, +3 per repeat | nothing: stops jab and kick | throw (14) |
| DUCK | 4 | nothing: evades jab and throw, earns an opening | kick (18) |
| THROW | 9 | block (14); recover (18) | jab, kick; duck evades it |
| RECOVER | 0 | nothing: +18 stamina if unhit, +6 if hit | any attack, at the higher damage |

Start at 100 HP and 60 stamina, with one power strike per fight. An unaffordable
move becomes EXHAUSTED: you pay nothing and stand open. The exact matrix and
resolution order are in [docs/combat.md](docs/combat.md).

## Five-minute quickstart

You need [uv](https://docs.astral.sh/uv/) and Python 3.12+. Nothing below needs
a wallet, a seed, a node or money.

```sh
git clone https://github.com/jonsggi/qdojo.git && cd qdojo

# Meet the six practice opponents
uv run qdojo combat npcs

# Fight one with the example planner; the seed is printed so you can rerun it
uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py" --out fight.json

# Re-derive that fight from its plans alone
uv run qdojo combat replay fight.json

# Benchmark a built-in policy against every NPC, both corners, 20 seeds each
uv run qdojo combat evaluate --policy mixed-v1 --seeds 20

# Readiness check for your own planner (spends nothing)
uv run qdojo combat doctor --planner "python3 examples/combat/planner_minimal.py"
```

Then try the full chain-shaped loop on a **local devnet** (the reference
contract on a fake chain, fake QU, synthetic identities; state in
`~/.qdojo/combat/`, or wherever `QDOJO_COMBAT_HOME` points):

```sh
uv run qdojo combat fighter register musashi
uv run qdojo combat bot run --fighter musashi --npc scout-v1 --spar kicker-v1 --ticks 300
uv run qdojo combat fighter show musashi
```

`bot run` queues, commits, reveals and settles within a spending budget, and
`--spar` adds a disclosed sparring bot so you have someone to fight. To look
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
| `apps/web/` | The static spectator site: `index.html` (combat), `legacy.html` (retired riddle arcade), `llms.txt` (agent briefing), `combat/` (browser engine and replay verifier) |
| `examples/combat/` | `planner_minimal.py`, a dependency-free planner |
| `prompts/combat/` | System prompt for the LLM planner |
| `scripts/` | Validation, economics, fixtures, soak and sample-data generators |
| `docs/` | Rules, protocol, guides and reports ([index](docs/README.md)) |
| `audits/` | Open audit findings from the riddle era |
| `dojo`, `dojo.cmd`, `dojo.ps1`, `examples/solvers/` | Legacy riddle onboarding and solvers; not a combat path |

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
| Fighter NFTs | Simulated (`AssetRegistry`); no real asset issued |
| Public demo arena | Live at qdojo.jonsggi.com: simulated chain, fake QU, operator-run bots |
| Qubic contract | Source passes Core's contract checker and replays the parity journals in core-lite's harness. **Not deployed** |
| Paid play | Not available. It needs a deployed contract, a release manifest and explicit authorisation |

Stage-by-stage detail: [roadmap](docs/roadmap.md). The retired riddle game is
kept read-only as Legacy ([archive](docs/archive/riddle-v0/INDEX.md)).

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
`docs/api.md` and `apps/web/llms.txt` is parsed by the test suite.

## Licence

The repository has no licence file yet. Ask the owner before reusing code or
artwork.
