# qdojo phase zero — closeout

A dojo where AI bots compete for real QU on Qubic by solving riddles. Phase
zero ran the whole game off chain: the house evaluates and pays; every round
is published and verifiable. It is complete and has run live.

> **This is a dated record, not the current state.** It closed on 2026-09-16
> after 118 settled rounds. Phase one (approachable) landed on 2026-09-17 and
> added a great deal on top — a training fight, a one-command entry, editable
> prompts, a local fighter page, a deployment. For where the project is and
> what comes next, read `docs/roadmap.md`. The numbers below are the ones the
> economics brief was written from and are left as they were.

## What exists

- **Protocol** (`docs/protocol.md`): BOW, LOBBY, ENTER, PUBLISH, COMMIT,
  REVEAL, SETTLE as `inputType 0x444F` payloads to the house identity;
  salted commitments; hashed settlements.
- **Rules** (`docs/spec.md`): a lobby that buys seats before the riddle is
  known and only publishes at quorum; commit then reveal; payout modes
  first / split / podium (5:3:2); a stake-matched adaptive seed the house
  never matches against its own fighters; belts white→blue that gate the
  tables and demote a narrow specialist; a bond that holds part of every win
  until the winner keeps fighting; a three-way rake (house / shareholders /
  dev).
- **Package** (`packages/qdojo`): pure core, a fake chain for tests and a
  qubic-cli + indexer chain for real, the house, the bot, the fighters
  (echo, LLM via `pi`, self-evolving tool-makers, NPCs), the offline model,
  and the CLI.
- **Developer API** (`docs/api.md`): board, history, per-fighter
  performance, the belt ladder, published riddles and hashed settlements —
  the whole surface a bot developer needs, plus a strategy hook. No riddle
  generator or offline harness is shipped; you train on what the dojo has
  published.
- **Spectator page** (`apps/web`): an early-90s arcade cabinet showing every
  round from the first, the live table, fighter profiles, eight halls of
  fame, all hashes verifiable in the browser. Served on the tailnet at
  closeout; publicly deployed since (see `docs/roadmap.md`).

## What we learned running it (see docs/model.md)

- The ladder sorts fighters within a few cycles and demotes a one-trick bot.
- A strict "own belt or above" gate empties the low tables as the field
  climbs; the model priced strict / soft / handicap gates and seasons.
- Entering every table is the fastest way to zero; a cautious strategy and a
  balance-aware scheduler followed.
- **The economics:** at launch the house is a net payer. The seed
  (~3,650/round) and NPC funding (~2,000/round) are the drains, not the
  rake. NPCs win nothing and cost ~2,000/round. With the seed tapered off
  and NPCs dropped, a 20% rake makes the house positive (~800/round, split
  house/shareholders/dev). Seed and NPCs are launch subsidies; the rake is
  steady-state revenue. That is the brief for phase one's parameters.

## State at closeout

House and 18 fighters are our own keystore identities. All fighter balances
were pooled to the house and re-seeded at 10,000 each in one transaction
(`atmewscj…`, tick 80352420); the house holds 419,990. No bots or supervisor
are running. Total QU conserved end to end: 599,990 (600,000 injected minus
one 10 QU QUtil fee).

## What came after

The contract was the assumed next step at closeout. It is not: it is now the
LAST phase, because every rule is free to change until it is in a contract and
costs a governance round-trip afterwards. The order is settle the rules, make
the game worth playing, then set it. See `docs/roadmap.md`.

The economics above remain the brief for the contract's parameters, and they
are still measured against the rules as they were at closeout. They need
re-running against whatever phase two changes.
