# Implementation plan: riddle game to combat

> **Purpose:** the original work packages P0–P8 for the combat pivot, with their acceptance criteria. \
> **Audience:** reviewers checking what each stage was meant to prove. \
> **Status:** historical (written 2026-09-21). P0–P7 are done on a simulated chain and the module layout in §3 now exists; current state is in the [roadmap](roadmap.md). Kept in place because code and contract READMEs cite its package numbers. \
> **Last reviewed:** 2026-09-25

## 1. Start here

Read [spec.md](spec.md), [combat.md](combat.md), [protocol.md](protocol.md),
[matchmaking.md](matchmaking.md), [competition.md](competition.md),
[api.md](api.md), [npcs.md](npcs.md), then [model.md](model.md).

The specification deliberately separates beat, round, fight and series.
A round is six simultaneous beats; a fight is at most three dependent rounds.
Three combat rounds MUST NOT be implemented as best-of-three independent fights.

Do not infer rules from animations, the old riddle evaluator, commentary in old
tests, or archive prose. Implement the matrix and numbered resolution steps.
Use the fixed canonical encodings; do not hash JSON plan text or host structs.

## 2. Current repository reality

The existing Python house, bot, solver, round, payload, belt, model and CLI
implement the riddle game. The current website reads riddle exports and animates
illustrative sparring. Signing, native transport, onboarding, portability,
settings and the arcade art are useful foundations; their correctness does not
establish the combat engine's correctness.

Do not delete working historical code/data as the first migration step.
Keep legacy tests passing until its supported namespace is formally retired.
Do not modify old settlements, recompute their winners, clear balances, relabel
old fighters as independent users, or treat archived liabilities as available funds.

## 3. Suggested module boundaries

These paths are a target layout, not files claimed to exist:

| New module/path | Responsibility |
|---|---|
| packages/qdojo/src/qdojo/combat/types.py | Strict state, plan, result and enum definitions |
| combat/rules.py | Load/freeze candidate parameters; digest checks |
| combat/engine.py | Pure beat/round/fight transitions; no I/O, RNG or money |
| combat/codec.py | Exact canonical game bytes and SHA-256 commitments |
| combat/matchmaking.py | Pure offer compatibility/order; explicit tick input |
| combat/rating.py | Integer updates, qualification, belt mapping |
| combat/series.py | Series/cup brackets, schedules and bounded outcomes |
| combat/ledger.py | Escrow, credits, rake, refunds and conservation |
| combat/protocol.py | Pure state machine, authority, nonces and deadlines |
| combat/store.py | Atomic snapshots/journal, schema/network migration |
| combat/bot.py | Planner protocol, secret-plan journal, restart and scheduler |
| combat/npcs.py | Versioned policies and reproducible training PRNG |
| combat/training.py | Local practice, evaluation, reports and counterfactuals |
| combat/export.py | Public schemas, confirmed evidence and redaction |
| contracts/ | Pinned Qubic source integration and equivalent C++ core |
| apps/web/combat/ | Combat data adapter, independent replay and views |
| packages/qdojo/tests/combat/ | Golden vectors, protocol/ledger/property scenarios |

Keep dependency direction: types/rules -> engine; codec independent of transport;
protocol composes engine/matcher/ledger/rating; adapters perform I/O.
Browser replay cannot import a winner from the server and call that verification.

## 4. Ordered work packages

### P0 — Spec artifacts and schemas

Deliver: machine-readable rules, JSON schemas, canonical byte layouts,
hand vectors, error enums, event/query/admin schemas and fixture profile.
Generate a digest file only from reviewed frozen artifacts.
Review every conflict before implementation. Complete admin ABI data structures
under the authority limits already specified; leave real keys/addresses unset.

Acceptance: byte layout round-trip, malformed input rejection, documented
examples parse, all active document links resolve, old provenance archived.

### P1 — Independent combat engines

Implement Python reference from the table and C++ pure core from the numbered
steps independently. A browser reader follows after fixtures stabilize.
No chain integration yet. Implement exhaustion, carry-over and simultaneous
KO before adding bots.

Acceptance: all hand vectors; side symmetry; 100,000 property cases; cross-
language fixtures; no float/time/random dependence. Store mismatching traces.

### P2 — Free training and NPCs

Ship local practice without wallet/NFT/network and all NPC profiles.
Implement the planner adapter, observation/response validation, history cache,
per-decision budgets, fixed fallback and evaluation reports.

Acceptance: a new owner can fight random-v1 immediately, reproduce a seed,
change a bot, compare versions, and inspect exactly why it lost.
NPC seeds/policies are frozen for evaluation; hidden hosted seeds stay private.

### P3 — Strategic validation before freeze

Run the full [model.md](model.md) campaign, best-response searches and ablations.
Do not start multiplying moves/features to explain away a failing baseline.
If changes are needed, increment the candidate, update docs/artifact/vectors,
rerun relevant gates and publish the failures as well as improvements.

Acceptance: release strategic gates pass; cost/compute and readable replay
results included. This milestone is not an external pilot or paid rollout.

### P4 — Fake-chain protocol, book and ledger

Implement ownership snapshots, exclusive locks, exact deadlines/nonces,
funded offers, bounded matcher, series, withdrawal credits and service-gap
generation. Use fake funds and explicitly controlled ticks.

Acceptance: restart/retry/race/failure cases; conservation for every terminal
path; both-player fault; overflow; stale owner; canceled/expired offer;
wrong-network and wrong-state commitments; no reveal withholding escape.

### P5 — Ratings, seasons, duels and cups

Add integer lifetime/season rating, placement, qualifications, per-pair limits,
named duel formats, seeded brackets, capacity reservations, check-in/replay/
abort and trophy-result records. Asset issuance remains gated separately.

Acceptance: epoch-boundary scenarios, series reset vs round carry-over, exact
entry/rake/sponsor refunds, transferred finalists and no arbitrary tiebreak.

### P6 — Spectator and owner experience

Wire the new namespace, book, battle state, trace-driven animations, static
replay, fighter scouting, NPC practice, budgets and obligations.
Retain the cabinet styling and historical riddle viewer behind a Legacy label.

Acceptance: rendering never influences result; reduced motion parity; no
secret leakage; actual HP distinct from time; verified/hash-only/unavailable
badges based on evidence; planned commands become real and parser-tested.

### P7 — Contract, native adapter and economics

Pin Core commit; prove SHA-256/QPI ownership/ABI/transfer behavior; port the
already-validated bounded state machine. Prove independent replay parity,
reserve-fault handling, worst-case cost/state size and account-capacity safety.
Freeze actual procedure IDs and signed transaction vectors only after ABI review.

Acceptance: platform contract verifier and contract tests; golden parity,
node confirmation/recovery exercises, economic report, capacity/timing manifest.
Existing crypto crosscheck is required if signer internals change.

### P8 — Migration, release checks and external onboarding

Inventory legacy custody: open rounds, carry, bonds, credits, keys and historic
records. Reconcile them in an explicit legacy closeout plan without assuming
this docs change authorizes sends. Keep a read-only archive and independent
combat state with zero implicit imported liabilities/rating.

Finish registration assets/rights, transfer tests, production manifest, TLS,
monitoring, archive availability, audit dispositions and documentation signature.
Only after these complete and separately authorized deployment is verified,
onboard the ten founding external owners to the complete product.

## 5. File-by-file treatment of existing code

| Existing area | Action |
|---|---|
| round.py, riddle.py, riddles.py, qubic_riddles.py | Legacy-only; do not extend as combat engine |
| payload.py, hashing.py | Preserve v0 compatibility; new combat codec/domain |
| belts.py, fees.py, model.py | Legacy behavior retained; new ratings/fee profiles/evaluation |
| bot.py, solver.py, spar.py | Reuse process patterns selectively; route new combat path explicitly |
| qubic/, chain/ | Reuse verified transport/signing; add tested contract calls |
| settings.py, portable.py, cockpit/dash | Reuse owner configuration/security; new combat schemas |
| house.py and private state | Preserve audited legacy obligations; contract becomes combat referee |
| apps/web/app.js and data | Separate combat adapter; never overwrite legacy exports |
| avatars.js, anim.js | Retain art; add trace-mapped missing poses in implementation phase |
| examples/solvers/, prompts/solver-*.md | Legacy; add new combat policy/prompt namespace |
| audits/ | Keep evidence; resolve/retire each finding with explicit rationale |

Do not alter private keys, .claude/, .infisical.json, unrelated worktrees,
services or live data as part of this documentation handoff.

## 6. Definition of done

All specified modes function with one deterministic fight engine; validation
passes; every money path conserves; official NPCs are labelled and unrated;
owners can train free and enforce spending; histories are replayable; all
production parameters are explicit; current docs match shipped interfaces.
A green old riddle test suite alone does not meet this definition.

No commit, deployment, signed publication, mint or funds movement is part of
the documentation task. Follow the repository's release authorization process.
