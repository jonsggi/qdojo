# Glossary

> **Purpose:** one meaning per word, across the docs, the CLI and the site. \
> **Audience:** everyone. \
> **Status:** reference. Game terms match the site's HELP screen (`viewHelp` in `apps/web/combat/app.js`); where a rule is summarised, [combat.md](combat.md) and [spec.md](spec.md) win. \
> **Last verified:** 2026-09-25.

## People and software

| Term | Meaning |
|---|---|
| **Owner** | The person who holds a fighter. Receives its winnings, sets its operator, pays its stakes |
| **Fighter** | A persistent identity that fights, carries a rating and record, and can change owners. On chain it will be a one-unit Qubic asset (NFT); today it is simulated |
| **Founding fighter** | One of the first fighters, gifted at launch. Provenance only: no combat advantage |
| **Operator** | The key an owner authorizes to act for a fighter (queue, commit, reveal). Usually the bot's signer |
| **Bot** | Owner-run software that makes spending decisions, keeps the secret plan journal, and commits and reveals on time |
| **Planner** | The program a bot runs once per round: observation in, plan out. It never signs or spends |
| **Plan** | Six actions plus an optional power slot for one round |
| **NPC** | A disclosed practice opponent (`random-v1`, `jabber-v1`, `turtle-v1`, `kicker-v1`, `mixed-v1`, `scout-v1`). Same stats as everyone; never in ranked play |
| **House** | The operator of the platform. Receives the house share of the rake; runs the demo bots |

## The fight

| Term | Meaning |
|---|---|
| **Beat** | One simultaneous action by each fighter |
| **Round** | Six beats from two sealed plans, resolved in one go. A fight has at most three |
| **Fight** | Up to three rounds; HP and resources carry between rounds |
| **Series** | One, best-of-three or best-of-five fights (duels). Each fight starts fresh |
| **HP** | Health, 0 to 100. Never resets between rounds. Zero is a knockout |
| **Stamina** | Pays for moves, 0 to 60. `RECOVER` and the break refill it |
| **Break recovery** | +10 stamina between rounds, capped at 60 |
| **Exhausted** | What an unaffordable move becomes: pays nothing, deals nothing, takes damage as an open target, recovers 6 |
| **Opening** | Earned by ducking a jab or throw, or by landing a clean jab. +4 damage on the very next beat if it lands; otherwise it expires |
| **Guard / guard streak** | Consecutive blocks. Each costs 3 more stamina than the last, up to 3 in a row |
| **Strain** | The 6 extra stamina a blocker pays when it blocks a kick. Never HP |
| **Power strike** | Once per fight: a marked `JAB`, `KICK` or `THROW` deals +4 for +4 cost. Spent even if it misses |
| **KO / DOUBLE_KO** | One fighter at zero HP / both on the same beat (a draw) |
| **HP / HP_TIE** | Result after round 3: higher HP wins / equal HP draws |
| **Unexecuted** | Actions revealed after a knockout. Shown, never counted as play |

## Protocol and chain

| Term | Meaning |
|---|---|
| **Commit** | Sending a SHA-256 hash of the plan, a secret salt and the fight context. Nobody can change a plan after seeing the other one |
| **Reveal** | Sending the salt and plan after the commit window closes; the contract checks them against the commitment |
| **Salt** | 32 random secret bytes that make a commitment unguessable. Never reused |
| **Tick** | The chain's clock. All deadlines are ticks. A countdown on the site is time left to act, never health |
| **Commit / reveal window** | 24 ticks to commit, then 12 to reveal (candidate timing profile) |
| **Timeout / forfeit** | Missing a commit or reveal deadline loses the whole contest to a compliant opponent. Shown as TIMEOUT, never as a knockout |
| **Double fault** | Both sides missed a deadline: no winner, stakes returned, a fault for each, no rating change |
| **Void** | The contract could not run (service gap): stakes returned, no fault, no rating change |
| **Ruleset / ruleset digest** | The exact combat parameters, and the SHA-256 that identifies them (`combat-v1-candidate-1`, `12085c86…`) |
| **Reference contract** | The Python contract in `combat/contract.py` that every other implementation must match |
| **Devnet** | A local, persistent fake chain running the reference contract with fake QU and synthetic identities |
| **Simulated chain** | `SimChain`: the devnet plus latency, dropped and reordered transactions, and execution fees |
| **Demo arena** | The public site's data source: the reference contract on a simulated chain with operator-run bots |
| **Manifest** | The deployment record naming network, contract, ruleset, profiles and recipients. No production manifest exists |

## Competition and money

| Term | Meaning |
|---|---|
| **QU** | Qubic's currency, in whole units. Everything in QDOJO today uses fake QU |
| **Offer** | A funded, expiring intent to fight: a ranked queue entry or a named duel challenge |
| **Book** | The public list of open offers |
| **Ranked** | Automatic pairing of compatible offers; the only mode that moves rating |
| **Duel** | A named challenge between two fighters, as a series, with an agreed stake. No rating change |
| **Cup** | A scheduled bracket with entry fees and optional sponsorship; check-in before each pairing |
| **Stake** | QU each side puts up for a contest |
| **Rake** | The platform's cut of paired stakes or cup entries (development value 500 bps), split between house, developer and shareholders |
| **Credit / withdraw** | Winnings are credited in the contract; the recipient withdraws the whole credit to itself |
| **Rating** | Integer, zero-sum, starting at 1000. Only ranked fights move it |
| **Placement / provisional** | A fighter's first 10 ranked combat fights; shown as PROVISIONAL, white belt |
| **Belt** | Display derived from rating: white, yellow (900), orange (1100), green (1300), blue (1500), brown (1800), black (2100) |
| **Epoch** | A Qubic epoch (the demo arena uses 2,400 ticks). Rate limits reset per epoch |
| **Season** | Four epochs with its own rating, standings and a trophy |

## On the site

| Term | Meaning |
|---|---|
| **REPLAY_MATCH** | Your browser recomputed the commitments and replayed every beat from the revealed plans, and everything matched. Chain inclusion is not proven |
| **COMBAT_VERIFIED** | Every check passed, including confirmation on chain. A same-source export cannot earn it |
| **HASH_MATCH_ONLY / UNVERIFIED / FAILED** | Only hashes could be checked / nothing could be checked / something did not match |
| **SAMPLE** | No live export was found, so the site shows a devnet sample |
| **STALE** | The live export has not been rewritten for over 5 minutes; the exporter may be down |
| **LEGACY** | The retired riddle arcade, kept read-only |
