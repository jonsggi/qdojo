# qdojo

A dojo for programmable fighters on Qubic. Owners build bots, study opponents'
published fights and compete through hidden action sequences.

**The project is pivoting to combat.** A fight has three connected rounds of
six simultaneous beats. Health and resources carry forward. Bots adapt between
rounds; a deterministic smart contract is intended to resolve actions and settle
the purse. Automatic matchmaking, duels, tournaments and free NPC training use
the same combat rules.

**Current status:** the combat system is specified, not implemented or deployed.
The existing Python CLI and website still run/display the legacy riddle game.
The new docs must not be read as a claim that a combat command already works.

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
| [Developer API](docs/api.md) | Planner interface, data, replay and planned commands |
| [Validation](docs/model.md) | Strategic depth, balance, exploits, latency and economics |
| [Roadmap](docs/roadmap.md) | Implementation order and release gates |
| [Operations](docs/operations.md) | Runtime authority, incidents and migration |
| [Decisions](docs/product-decisions.md) | Preserved/changed decisions and open launch values |

Combat is deterministic; surprises come from concealed plans and adaptive or
randomized policies. No purchased stats or random damage rolls. Free NPC
practice requires no wallet or fighter asset. Paid competition retains the
persistent fighter-registration plan.

## Repository today

- packages/qdojo/: legacy game plus reusable transport, signing and bot tooling.
- apps/web/: arcade spectator page, fighter artwork and current riddle data.
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
