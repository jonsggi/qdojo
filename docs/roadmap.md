# Combat pivot roadmap

Updated 2026-09-23. Active plan; the
[old riddle roadmap](archive/riddle-v0/docs/roadmap.md) is historical.
See [pivot-plan.md](pivot-plan.md) for file-level work and acceptance criteria.

## Status, 2026-09-23

| Stage | State | Evidence |
|---|---|---|
| P0 | Done | Packaged ruleset with digest check; codec reproduces the frozen commitment fixture; admin ABI; event body frozen |
| P1 | Done | Python, C++ (`contracts/combat_core`) and browser (`apps/web/combat/engine.js`) engines agree on all 10,000 frozen fights |
| P2 | Done | `qdojo combat train/replay/npcs`; six NPCs whose browser port matches 900 frozen plan fixtures; planner subprocess with fallback |
| P3 | Strategic gates 11/11 on held-out seeds; economics, latency and readability not yet measured | [validation report](validation-report.md), [status and caveats](validation-status.md) |
| P4 | Done on fake chain | `combat/contract.py` reference, devnet, owner bot with plan journal and budgets; fuzzed conservation |
| P5 | Done on fake chain | Ratings, placement, seasons, duels, cups with replay/postponement/abort |
| P6 | Done against sample data | `apps/web/combat.html`: replays re-derived in the browser, per-check verification badges, practice |
| P7 | C++ port and parity in progress; **not deployed** | Local Qubic testnet needs a 16 GB host with clang (this host: 7 GB, no clang); mainnet inclusion needs a computor proposal and IPO |
| P8 | Inventory and plan only | [legacy-closeout.md](legacy-closeout.md); no sends executed |

"Done" means implemented and tested locally. It never means paid activation,
which still needs a release manifest, a deployed contract and authorisation.

## Completed foundation

- Legacy riddle engine, solver/bot/house, history and native chain integration.
- Arcade spectator styling, fighter sprites and basic animation clips.
- Owner onboarding, local settings, training patterns and portability work.
- Combat direction and candidate specification, with NPC practice and validation plan.

This list does not mark combat behavior, assets or a contract as delivered.

## Dependency sequence

| Stage | Deliverable | Gate to advance |
|---|---|---|
| P0 | Rules artifact, schemas, byte layouts and fixtures | No ambiguous mechanics or encoding |
| P1 | Independent pure Python/C++ combat cores | Arithmetic, symmetry and fixture parity |
| P2 | Free practice, NPCs and bot interface | Immediate reproducible local fighting |
| P3 | Adversarial balance and optimization campaign | Strategic/pace/readability gates pass |
| P4 | Fake-chain commit/reveal, book, ledger and recovery | Races, failures and conservation pass |
| P5 | Ratings, seasons, duels, cups and trophy records | Bounded event/ownership/accounting cases pass |
| P6 | Combat spectator/owner UI and native CLI flow | Replay verification and spending controls work |
| P7 | Qubic contract and execution-cost validation | Pinned platform conformance and release manifest |
| P8 | Legacy closeout, release and onboarding | Audit/asset/operations gates satisfied |

P4 scaffolding and P6 read-only prototypes may proceed while P3 runs, but
neither freezes an unvalidated ruleset or authorizes paid combat. Contract
design constraints guide all stages; deployment follows a validated reference.
No external money pilot is introduced as a substitute for the complete product.

## Release includes

Three-round sequence combat, hidden plans and equal-access power timing;
free random/style/adaptive NPC practice; ranked book; persistent fighter
ownership; combat ratings and belts; public replays and scouting; duels;
scheduled cups; four-epoch seasons/trophies; direct contract settlement;
owner budgets; independently checkable results.

## Deferred

Riddle catalogue expansion, riddle author revenue, oracle/EVM judging,
arbitrary verifier/bot execution in the contract, combat equipment/buffs,
paid NPC opposition, positional movement, additional ranked rulesets,
spectator betting and marketplace integration.

These are not half-implemented launch promises. Each future mechanic needs
its own exact rules, resource/counterplay analysis, cost bounds and new version.

## Release values still needed

The [decision register](product-decisions.md) owns open production parameters.
Missing live addresses/prices never block free local implementation; they
keep paid activation disabled. Archived riddle economics are not the combat
business case.

After complete release, observe independent players' improvements, queue
waits, repeated play, spending, NPC use and actual operating costs. Internal
bot populations and gifted registrations cannot establish willingness to pay.
