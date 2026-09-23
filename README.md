# qdojo

A dojo for programmable fighters on Qubic. Owners build bots, study opponents'
published fights and compete through hidden action sequences.

**The project is pivoting to combat.** A fight has three connected rounds of
six simultaneous beats. Health and resources carry forward. Bots adapt between
rounds; a deterministic smart contract is intended to resolve actions and settle
the purse. Automatic matchmaking, duels, tournaments and free NPC training use
the same combat rules.

**Current status (2026-09-23):** combat is implemented and tested locally.
The engine, NPCs, free training, bot, reference contract, devnet, CLI and
spectator page all work. The contract is **not deployed**: paid play needs a
deployed Qubic contract, a release manifest and authorisation. The riddle game
and its site remain available, labelled Legacy. Progress by stage is in
[the roadmap](docs/roadmap.md); strategic gate results are in
[the validation report](docs/validation-report.md).

Try it with no wallet:

```sh
uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"
uv run qdojo combat fighter register musashi
uv run qdojo combat bot run --fighter musashi --npc scout-v1 --spar kicker-v1 --ticks 300
python3 -m http.server -d apps/web 8000   # then open /combat.html
```

## Implementation handoff

Start with [the specification](docs/spec.md) and
[the pivot implementation plan](docs/pivot-plan.md).

| Document | Purpose |
|---|---|
| [Combat rules](docs/combat.md) | Complete action matrix, resolution order, resources and hand vectors |
| [Matchmaking](docs/matchmaking.md) | Funded offers, automatic pairing, expiry and limits |
| [Competition](docs/competition.md) | Ratings, belts, seasons, duels and cups |
| [NPCs](docs/npcs.md) | Random/style/adaptive practice opponents |
| [Protocol](docs/protocol.md) | Commit/reveal bytes, deadlines, authority and recovery |
| [Developer API](docs/api.md) | Planner interface, data, replay and the combat CLI |
| [Validation](docs/model.md) | Strategic depth, balance, exploits, latency and economics |
| [Roadmap](docs/roadmap.md) | Implementation order and release gates |
| [Operations](docs/operations.md) | Runtime authority, incidents and migration |
| [Decisions](docs/product-decisions.md) | Preserved/changed decisions and open launch values |

Combat is deterministic; surprises come from concealed plans and adaptive or
randomized policies. No purchased stats or random damage rolls. Free NPC
practice requires no wallet or fighter asset. Paid competition retains the
persistent fighter-registration plan.

## Repository today

- packages/qdojo/src/qdojo/combat/: engine, codec, NPCs, planner, training,
  evaluation, reference contract, devnet, bot, export and CLI.
- contracts/: independent C++ engine core and the contract port.
- apps/web/combat.html: combat spectator, verification and practice.
- packages/qdojo/: legacy game plus reusable transport, signing and bot tooling.
- apps/web/: arcade spectator page, fighter artwork and legacy riddle data.
- docs/: authoritative combat design; archive/riddle-v0 preserves old specs.
- examples/solvers/ and prompts/solver-*.md: legacy riddle solvers/prompts.
- audits/: existing findings remain open until explicitly resolved or retired.

Existing read-only CLI help still works:

```sh
uv run qdojo bot --help
```

The [archived README](docs/archive/riddle-v0/README.md) contains the old
onboarding and platform notes. Its fight/house commands concern the riddle
system; do not use them as combat onboarding.

For contributors, read [contributing.md](docs/contributing.md). Validate the
documentation and candidate arithmetic with the reference checks described in
[the handoff](GPT6_HANDOFF.md). Run `make test` before committing.
