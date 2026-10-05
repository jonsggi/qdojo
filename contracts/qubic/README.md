# contracts/qubic: QDOJO in the Qubic Core contract dialect

This is package P7 of [docs/pivot-plan.md](../../docs/pivot-plan.md), step
"transliterate into the QPI dialect and prove it inside Core". It turns the
parity-tested bounded port [`../combat_contract/combat_contract.h`](../combat_contract/combat_contract.h)
into a real Qubic Core contract, and checks it with Qubic's own tooling as far
as this host allows.

| File | Contents |
|---|---|
| `QDOJO.h` | The contract, in Core's restricted C++ dialect. It has one `Dispatch` user procedure taking `Array<uint8,512>`, `INITIALIZE`, `BEGIN_TICK`, `END_TICK`, and ten bounded query functions. SHA-256 is implemented inside the contract. The combat-v1 candidates 1, 2 and 3 are compiled-in tables keyed by digest. |
| `test_qdojo_core.cpp` | A GoogleTest for Core's contract test harness (`test/contract_testing.h`). It replays every reference journal through the QPI-built contract (and any journal named in `QDOJO_EXTRA_JOURNALS`). Install it as `test/contract_qdojo.cpp`. |
| `core_harness.py` | Reproduces every check below from pinned upstream commits: `verify`, `test`, `core-syntax`, `all`. |

Summary. Commit and tool versions are in [Pins](#pins).

| Check | Tool | Result |
|---|---|---|
| Dialect compliance | qubic/contract-verify, the SHA that Core's CI pins | **PASSED** (2026-09-30). Six injected violations are all rejected, so the tool really parses the whole file. |
| Compiles inside Core's test harness | core-lite (the Linux/clang port of Core), clang 18 | **Yes.** QDOJO.h has no errors and 18 warnings, all `-Wunused-parameter` from the QPI macros. |
| Journal replay through the real contract | core-lite GoogleTest `qdojo_core_tests`, `_c2`, `_c3` | **All 8 committed journals (candidates 1, 2 and 3) and the live arena's candidate-3 journal (117,600 ticks, 92,132 calls) end at the reference's final event digest.** On each journal the call results and the event digest also match the C++ port after every step, with the port built for that journal's ruleset. |
| Ledger and QU conservation after every step | the same test, through the `GetLedger` query and Core's spectrum | balance == liabilities == the contract's real QU balance; every fault counter is 0 |
| Compiles against pinned qubic/core | clang syntax-only compile of the same test | **0 errors in QDOJO.h or the test.** Core's own headers produce 324 errors, because Core's test build is MSVC-only. |
| Local testnet node with QDOJO | core-lite `TESTNET` + `TESTNET_LITE_RAM` | **Built and launched, but could not run.** The node reports `Total RAM required 12 GB`, and under a 3 GB cap it was OOM-killed about 10 s after launch. See [Local testnet](#local-testnet-core-lite-step-4). |

## Pins

| What | Repository | Commit |
|---|---|---|
| Qubic Core, as read and syntax-checked | github.com/qubic/core | `e3ef766686e5d69a2bdd17a12213f1d21d145778`, 2026-09-23, "Merge pull request #1011", EPOCH 232 |
| Qubic Core Lite, where the test was built and run | github.com/qubic/core-lite | `5ad97af4b1ccb077580a39abfbe1891783d93c78`, 2026-09-23, "update params for epoch 232 / v1.305.0" |
| Contract verification tool | github.com/qubic/contract-verify | `970ce102d56df53b68f1b8fa65b2dd445d5c9d81` (tag v1.2.4). Core's `.github/workflows/contract-verify.yml` pins this exact SHA. |
| CppParser, the verifier's submodule | github.com/satya-das/cppparser | `3b5801f7389fcad3b8b1865d5ca10b1141d1c9e5` |
| GoogleTest | fetched by Core's CMake | v1.16.0 |
| Compiler | Ubuntu clang | 18.1.3 |

core-lite is the upstream Linux port of Core, and it is synced to the same
epoch-232 release. Its QPI differs from the pinned Core only in these ways:

- clang portability (`typename` in the oracle and proposal templates);
- hooks for its Wasm host bridge;
- TESTNET-only ifdefs;
- the alignment of the contract invocation buffer.

None of these touch the QPI surface QDOJO uses. That surface is `Array`, `id`,
`setMemory`, `div`/`mod`, `AssetOwnershipIterator`, `qpi.tick`,
`qpi.invocator`, `qpi.invocationReward`, `qpi.transfer` and `SELF`.

## How the dialect is met

Core forbids the following in a contract:

- `#include`, pointers, `[ ]`, `/` and `%`;
- string and char literals, floating point;
- local variables and globals;
- `...` and `__`.

`combat_contract.h` uses all of these. The transliteration handles them as
follows.

- **Helpers are static member functions.** They take `StateData&` and a
  scratch struct `Ctx&`. Core's accepted contracts `Pulse.h` and
  `QThirtyFour.h` use the same pattern.
  - `Ctx` holds every helper's temporaries, one field group per helper.
  - The helper call graph has no recursion, so no helper is ever live twice,
    and one `Ctx` per entry point is enough.
  - `Ctx` lives in the entry point's locals: 27,576 bytes. `END_TICK_locals`
    is 29,112 bytes, under the 32,768-byte `MAX_SIZE_OF_CONTRACT_LOCALS`.
- **There are no `CALL`s.** Nothing crosses the QPI call machinery, so the
  nested-contract-call depth is 1. The concern in the port README about 10
  nested calls, "END_TICK → … → sha compress", is moot: those are now plain
  C++ calls of static helpers.
- **Tables are `Array<T, 2^N>`.** `Array::get` returns a const reference, so
  every record is changed by copy, edit, `set`. Records that the reference
  holds by reference across helper calls become explicit working copies with
  fixed store points:
  - `endFight` stores the fight before anything can evict its slot, and the
    caller never stores it again;
  - `newFight` takes the contest working copy and sets `currentFight` on it;
  - the cup being ticked is `Ctx::cupW`, and `scheduleLevel` stores it before
    `fightsInUse` reads every running cup's reservation from state.
- **SHA-256 is in the contract** (FIPS 180-4, 64 rounds; `shaK` is a switch
  over the round constants). The combat-v1 digests (event, context,
  round-state, commitment, bracket) are streamed byte by byte, with no
  526-byte context buffer. The domain tags, the genesis digest, the ruleset
  digest and the event-body ASCII strings ("COMBAT", "FORFEIT", …) are
  `uint64` constants generated from the reference strings, because literals
  are forbidden.
- **Byte order.** Identities are `id`, and bytes are read with shifts from
  `id.u64._k`. The "smaller fighter id" order is byte-lexicographic
  (`idCmp` compares byte-swapped words), never `m256i operator<`.
- **`div` and `mod` carry explicit template arguments**, as in `div<sint64>`.
  With a bare `div(sint64, sint64)`, the C library's `lldiv_t div(long long,
  long long)` wins overload resolution in any translation unit that includes
  `<cstdlib>`, and the test harness does.

## Drift against the reference (audit of 2026-09-30)

The reference is `packages/qdojo/src/qdojo/combat/contract.py` with
`engine.py`, `ledger.py`, `matchmaking.py`, `series.py`, `rating.py` and
`codec.py`. The portable C++ (`contracts/combat_core`, `contracts/combat_contract`)
is proven equal to it by `make cpp-test` and `make contract-test`; QDOJO.h
transliterates `combat_contract.h`. Commit `1064e711` wrote QDOJO.h; `f8a734ed`
mirrored the pair limits and the expired-offer sweep. This is what had drifted
since, and what was done about it.

| Area | Reference today | QDOJO.h before | Now | On chain? |
|---|---|---|---|---|
| Engine: rulesets | Candidates 1, 2, 3; the live arena runs candidate 3 (`cf19b7cf…`: 9 actions, LAST_STAND 7, FEINT 8, HP 120, stamina 48, guard-break opening 2, stand bonus) | Candidate 1 only, hard-coded | **Ported.** Candidates 1–3 as tables keyed by digest; INITIALIZE takes the manifest digest's table (unknown digest: `initOk = 0`) | Yes |
| Engine: reason bits 15–17 | Descriptive trace fields; no rule reads them | Not computed (bits 0–14 neither) | Constants defined, not computed: the contract publishes plans and end states (REVEALED, ROUND_RESOLVED) and readers rebuild the trace | No (reader-side) |
| Plan decoding | `Plan.of` accepts ids 0–5, 7, 8 under every ruleset; the ruleset's legality is BAD_PLAN after the commitment check | Rejected ids > 5 at decode: a reveal with LAST_STAND and a wrong salt got BAD_PLAN instead of BAD_COMMITMENT (the C++ port too) | **Fixed** in both C++ files; covered by `scenarios.journal` | Yes |
| Pair limits, expired-offer sweep | Manifest fields; expired ranked offers closed every matching tick | Already mirrored (`f8a734ed`) | — | Yes |
| Fees and tiers | Up to 4 fee profiles (rake, house/dev/share split) and 8 tiers from the manifest; live: tiers 5,000/20,000, profiles 5% and 10% | Same logic; compiled manifest was the dev fixture (one 1,000 QU tier, one profile, timing 24/12, 10,000-tick epochs) | **Compiled manifest = the live demo-c3 economics** (below). The logic was already equal | Values are the release manifest's |
| Duel stake multiples, cup entry 2×, sponsorship 0.1× and its withholding rule, market activity | Arena policy (`live.EVENTS`), carried out by the admin and the bots | — | Not ported | No (operator policy) |
| Cups, duels, series | Bracket, byes, check-in, replay, postponement, prizes, aborts; SINGLE/BO3/BO5 | Equal (`scenarios.journal`, the fuzz journals) | — | Yes |
| Seasons | Stats, ratings, standings with the specified thresholds (12/4/3/3) | Equal (`GetStandings`) | — | Yes |
| Scaled qualification | `Qualification(scale=True)` for the demo profiles: a query-side rule outside the manifest | Not present | Not ported. `GetStandings` keeps the specified thresholds; the export applies the demo rule | No (query-side; port it only if it becomes the specified rule) |
| Belts, titles | Display only (`rating.belt_info`, `titles.py`) | Not present | Left out | No |
| Fighter asset binding | Ownership by fighter id from the NFT ledger | issuer = fighter_id, name `QDOJOF`: an asset nobody can issue | **Fixed.** AdminBindAsset (opcode 103) names issuer and asset name; `ownerOf` reads that asset. Opcode 100 keeps the interim binding for simulated arenas | Yes |
| NFT market and issuance | `nft.py`: QDOJO-managed one-share assets, asks, escrowed bids, fees, royalty, contest lock, deferred settlement, art anchor | None | Not ported (see [What remains](#what-remains), item 5) | Yes, under the recommended model |
| Procedure and function IDs | — | "Placeholders" | Frozen as the v1 ABI: `Dispatch` 1, queries 1–10. The network assigns the contract index, not these | Yes |
| Construction epoch | — | 240 in the harness registration; testnet at 232 | 232 (`core_harness.py` `CONSTRUCTION_EPOCH`) | Deployment value |
| Execution fees | `chainsim.FeeModel` simulates them; the arena funds a reserve | None | Not ported (the real reserve is Core's) | Policy open |

## Deviations the chain forces (behaviour otherwise identical)

- **The manifest is compiled in.**
  - `INITIALIZE` loads a TEST PROFILE (`loadDefaultManifest`): the fuzz
    journal's synthetic test identities, `contractId = SELF`, and the live
    arena's demo-c3 economics: ruleset candidate 3
    (`QDOJO_MANIFEST_RULESET`), timing 9/8, tiers 5,000 and 20,000 QU, fee
    profiles 1 (5% rake) and 2 (10%), 2,400-tick epochs from the construction
    tick, four-epoch seasons, a 300-tick closeout, 3 rated starts per pair per
    epoch and a 60-tick rematch gap. It is not a release manifest: the
    identities and `network_id` must be replaced.
  - A test may write `StateData::m` and set `manifestLoaded` before
    `INITIALIZE`. On chain the state arrives zeroed, so the compiled profile
    is always used. The harness loads each journal's header this way, so
    journals of every ruleset and profile replay in one build.
  - The checks in `init` are unchanged, plus the ruleset lookup. A failing
    manifest leaves `initOk = 0`. Every entry point is then inert, and
    `Dispatch` hands the attachment straight back.
- **The rulesets are tables keyed by digest.** `rulesetOf` maps the three
  packaged digests to `StateData::ruleset`; the engine's per-ruleset
  functions (`hpOf`, `staminaOf`, `openingDamage`, `powerDamage`,
  `maxOpening`, `isSubmitted`, `baseCost`, `damage`) read it. The portable
  port selects one ruleset at build time instead (`QDOJO_RULESET`); both are
  allowed because a deployment only ever admits its manifest's digest. The
  table costs one state byte and no loop bound; it lets one binary replay every
  journal.
- **`Host::owner_of` becomes `ownerOf`.**
  - It reads the single owner (shares > 0) of the fighter's registry asset,
    the (issuer, name) its AdminBindAsset named, through
    `AssetOwnershipIterator`. For the legacy AdminRegisterAsset the asset is
    issuer = `fighter_id`, name `QDOJOF`.
  - Every managing contract counts, so the owner is found whether QDOJO or QX
    manages the share.
  - No registry entry, no record (a burned share), several owners, or a
    NULL_ID owner means "unavailable" (BAD_STATE). `scenarios.journal` now
    covers this path: the harness burns the share.
- **`Host::transfer` becomes `qpi.transfer(...) >= 0`, called only by `Dispatch`.**
  - The reference transfers in exactly two places: the refund payback and
    `Withdraw`. Both pay the invocator, and both are the last action of the
    step, or of the handler before the nonce is recorded.
  - So `dispatchBegin`, `withdrawEnd`/`dispatchFinish` and
    `refundBegin`/`refundFailed` split the reference flow at those points, and
    `Dispatch` makes the transfer between them.
  - In Core (`qpi_spectrum_impl.h __transfer`), a failure returns a negative
    value before touching any balance, so "restore on failure" holds.
- **The attachment is counted once, in `Dispatch`.** There is no
  `POST_INCOMING_TRANSFER`. QU sent by a plain transfer (inputType 0) are not
  a liability and not in `balance`.
- **The `Work` counters of the port are dropped.** The `Faults` counters stay
  in state, and the test asserts they are zero.
- **The proposed `NOT_DIRECT` check (invocator != originator) is not
  implemented.** It is not in the reference, and the task requires identical
  semantics.
- **Queries.** These query functions are registered:

  <!-- sync:begin abi (docs/reference/check_sync.py: REGISTER_USER_FUNCTION in QDOJO.h) -->
  | ID | Query | Returns |
  |---:|---|---|
  | 1 | `GetService` | |
  | 2 | `GetAccount` | |
  | 3 | `GetEvents` | up to 64 events per page |
  | 4 | `GetFighter` | |
  | 5 | `GetOffer` | |
  | 6 | `GetFight` | |
  | 7 | `GetContest` | |
  | 8 | `GetCup` | |
  | 9 | `GetStandings` | the current or previous season; 16 rows and 16 playoff ids |
  | 10 | `GetLedger` | balance, the sum of liabilities, faults |
  <!-- sync:end abi -->

  `Dispatch` is user procedure 1. These IDs are the contract's own ABI and are
  frozen for v1; a new query takes the next free number. What the network
  assigns is the contract index (the next free one is 31 at qubic/core
  `e3ef766`), which fixes the contract identity.

## Verification: qubic/contract-verify

```
$ contractverify contracts/qubic/QDOJO.h
Contract compliance check PASSED
```

Negative controls: `core_harness.py verify` injects one forbidden construct at
a time deep inside the file. Every variant is rejected with the expected
message:

| Injected violation | Verifier message |
|---|---|
| `/` in `finishSide` | `Division operator / is not allowed` |
| a local in `emit` | `Local variables are not allowed, found variable with name z` |
| `[0]` in `GetEvents` | `Plain arrays are not allowed` |
| a string in `GetStandings`, the last function | `String literals are not allowed` |
| `%` in `lockRoster` | `Modulo operator % is not allowed` |
| `*(&t)` in `endTick` | `Pointer dereferencing (unary operator *) is not allowed` |

The verifier checks syntax rules only.

- It does not check the 10-deep call limit. QDOJO makes no `CALL`s.
- It does not check the locals limit. QPI's own `static_assert`s enforce that
  at compile time.
- It does not check the semantics. The replay below does.

## Tests inside Core's harness (core-lite, Linux)

`test_qdojo_core.cpp` drives the contract only through Core:

- `INIT_CONTRACT`, then `callSystemProcedure(INITIALIZE / END_TICK / BEGIN_TICK)`;
- `QpiContextUserProcedureCall` for `Dispatch`;
- `callFunction` for the queries.

Each journal record maps to a Core action:

| Record | What the test does |
|---|---|
| `start` | Writes the journal's manifest into the zeroed state, then runs `INITIALIZE` at the start tick. |
| `owner` | Moves the fighter's one-unit asset with Core's `transferShareOwnershipAndPossession`, issuing it first if needed. The asset is the one the journal's admin frames bind (a pre-scan applies the contract's binding rules): the (issuer, name) of AdminBindAsset (103), or issuer = fighter id, name `QDOJOF` for AdminRegisterAsset (100). `"owner": null` burns the share (a transfer to NULL_ID), so no owner record holds it. |
| `mint` | `increaseEnergy`. |
| `call` | The attachment moves from the caller's spectrum entry to the contract, and `Dispatch` runs at `system.tick = t`. |
| `fail` | While a failing caller's `Dispatch` runs, the contract's QU are parked on another entity. `qpi.transfer` then really fails, for insufficient balance. |
| `end` | `END_TICK` at t, then `BEGIN_TICK` at t + 1. |

After every step the test checks:

- through the real `GetLedger` query: balance == liabilities, no negative
  credit, and all five fault counters zero;
- the contract's spectrum balance == its ledger balance;
- with `QDOJO_LOCKSTEP_PORT` (on in the harness build): `combat_contract.h`
  runs next to the contract, and every call's `(code, op, target, refunded)`,
  the event count, the event digest and the balance must be equal.

At the end it checks:

- the final event digest from `GetService` against the journal's recorded
  reference digest;
- that `GetEvents` returns the last events;
- `GetStandings` for seasons 1 and 2 against the port's `query_standings`.

`core_harness.py test` builds three binaries from the same sources:
`qdojo_core_tests` (port built for candidate 1), `qdojo_core_tests_c2` and
`qdojo_core_tests_c3`. QDOJO.h replays every journal in each; the lockstep
port only follows journals of its own ruleset. The harness runs all tests in
the first binary, then the `*C2*` and `*C3*` tests in the other two, so every
journal is replayed both against the reference digest and in lockstep with
the port.

| Journal | Ruleset | Written by | Covers |
|---|---|---|---|
| `scenarios` | 1 | `scripts/combat-contract-scenarios.py` | cups, capacity, strangers; since 2026-09-30 also AdminBindAsset (binds, rejections, a sale, a burned share) and a candidate-1 reveal carrying LAST_STAND |
| `fuzz-1`, `fuzz-2`, `season`, `demo-profile` | 1 | `scripts/combat-sample-data.py` | random traffic, a bot season, non-default pair limits |
| `fuzz-c2` | 2 | `scripts/combat-contract-journals.py` | random traffic, 1,000 ticks, power slots |
| `fuzz-c3` | 3 | same | random traffic, 2,000 ticks, all eight actions (153 LAST_STAND and 145 FEINT reveals), power slots |
| `season-c3` | 3 | same | NPC bots on the demo-c3 profile, 1,500 ticks (44 LAST_STAND, 69 FEINT) |
| live arena (not committed) | 3 | `scripts/combat-journal-from-devnet.py ~/.qdojo/combat/arena OUT` | the live arena from tick 1 to 117,601: 92,132 calls, 116,768 events |

Result on this host (2026-09-30, `QDOJO_EXTRA_JOURNALS=<live copy> make qubic-core-test`,
Release, core-lite 5ad97af, clang 18; `rc=0`):

```
sizeof(QDOJO::StateData) = 1521208 bytes (1485.6 KiB); MAX_CONTRACT_STATE_SIZE = 1073741824
  fighters 1024 x 496, assets 2048 x 80, accounts 2048 x 96, events 2048 x 184, pairs 4096 x 40
  offers 128 x 296, contests 32 x 496, fights 32 x 296, cups 8 x 5976
locals: Ctx 27672, Dispatch 27720, END_TICK 29208, BEGIN_TICK 27672, INITIALIZE 27672 (limit 32768)
scenarios.journal (ruleset 12085c86a61ffd10..., QDOJO table 1, lockstep port on): 1938 records, 312 calls, 1542 END_TICKs, 450 events, balance 51609 QU; codes 0x287 2x3 4x6 7x5 10x1 12x2 18x2 19x1 23x2 24x1 25x1 29x1
    final event digest dc581744c20ac7f7337c05b6acfbd7f4dfaf0451b244e6fe13d30acf13c4d340 MATCH
fuzz-1.journal     (table 1, lockstep on)  final event digest 8738c597…1daaca MATCH
fuzz-2.journal     (table 1, lockstep on)  final event digest 4cc7979d…da26318 MATCH
season.journal     (table 1, lockstep on)  final event digest 37579348…dcdc19a6f MATCH
demo-profile.journal (table 1, lockstep on) final event digest 40eac55d…ff519f6 MATCH
fuzz-c2.journal    (table 2)  1662 records, 623 calls, 707 events   final event digest 835e4a89…be145d8a MATCH
fuzz-c3.journal    (table 3)  3350 records, 1292 calls, 1466 events final event digest 662b43f7…b140af17 MATCH
season-c3.journal  (table 3)  2111 records, 596 calls, 946 events   final event digest e11f0f0e…fb256428 MATCH
live-c3.journal    (table 3)  210398 records, 92132 calls, 117600 END_TICKs, 116768 events; codes 0x73765 7x214 9x6 12x36 13x43 14x18038 18x4 27x26
    final event digest 9ed25db77d0a54934ee7122c0844995aab0617602ca576226078c5ba09cba65f (reference 9ed25db7…) MATCH
[  PASSED  ] 11 tests.                                   (qdojo_core_tests)
fuzz-c2.journal (lockstep port on) MATCH   [  PASSED  ] 1 test.    (qdojo_core_tests_c2)
fuzz-c3, season-c3, live-c3 (lockstep port on) MATCH   [  PASSED  ] 3 tests.   (qdojo_core_tests_c3)
test: every journal replayed through QDOJO.h in Core's harness; lockstep with the port for each ruleset
```

Full log lines are abbreviated here; the harness prints every digest in full.
The live journal also replays in the portable port
(`contracts/combat_contract/test_contract_c3 <copy>`: PASS, same digest).

In the scenarios journal, code 29 is `TRANSFER_FAILED`. That result is
Core's real `qpi.transfer` failing: a withdrawal fails, then is retried.

The failed direct payback in the same journal also goes through Core. The
`REFUND_CREDIT` event and the digest match.

The earlier run (2026-09-24, candidate 1 only) reproduced these results from
fresh shallow clones with `core_harness.py all --jobs 1`. On 2026-09-30 the
three targets were run one by one (`make qubic-verify`, `make qubic-core-test`,
`make qubic-core-syntax`), from a fresh core-lite and core checkout.

Time spent in the contract, measured around Core's call wrappers on this host
(AVX-512, Release, one run, with other jobs on the machine). The averages are
stable between runs. The maxima are noisy. This table is from the
candidate-1 run of 2026-09-24; on 2026-09-30, with a parallel build on the
two CPUs, the averages were 9–34 µs per Dispatch and 1.3–9 µs per END_TICK
over all journals (the live journal: 14.3 µs and 6.6 µs).

| Journal | Dispatch avg | Dispatch max | END_TICK avg | END_TICK max |
|---|---:|---:|---:|---:|
| scenarios | 14.7 µs | 447 µs | 2.0 µs | 614 µs |
| fuzz-1 | 9.8 µs | 72 µs | 1.7 µs | 48 µs |
| fuzz-2 | 10.4 µs | 203 µs | 1.7 µs | 26 µs |
| season | 10.0 µs | 44 µs | 1.3 µs | 2033 µs |

Core then rehashes the dirty state with K12, and QDOJO dirties it every tick.
This takes about **1.4 ms per tick** for the 1.44 MB state (2026-09-24,
idle host; 3.2 ms measured on 2026-09-30 for 1.52 MB with a build running
beside it), which is about 1000× the average END_TICK. That confirms the port README's item 4: the state
digest is the dominant recurring cost.

### Negative controls for the replay

A deliberately broken QDOJO.h was built into the same harness to see whether
the replay catches it.

| Mutation | Result |
|---|---|
| JAB vs RECOVER deals 13 damage instead of 12 | **Detected.** fuzz-1 diverges from the port at tick 52. The first diverging event is `ROUND_RESOLVED`, the next call's result differs, and the final digest mismatches. |
| `scheduleLevel` does not store the cup before `fightsInUse` | **Not detected**, and it cannot be. When a level is scheduled, the stale state copy holds the same reservation (0) and the same counted status, because every pairing has decremented `reserved` before `advanceLevel`. The store is kept as a safe aliasing rule. |
| `ownerOf` treats a NULL_ID owner as available | **Not detected** (2026-09-24): no journal had an `owner: null` record. Since 2026-09-30 `scenarios.journal` burns a bound fighter's share and expects BAD_STATE, so the path is covered. |
| (2026-09-30) FEINT earns opening 1 instead of the guard-break 2 | **Detected.** fuzz-c3 and season-c3 end at other digests. |
| (2026-09-30) plan decoding rejects action ids 7 and 8 again | **Detected by the lockstep only.** At tick 1522 of `scenarios` the contract answers BAD_PLAN at decode where the port answers BAD_COMMITMENT (a wrong salt) and then BAD_PLAN (op 8). Result codes are not in the event digest, so the final digest still matches; the call-result comparison catches it. |
| (2026-09-30) `ownerOf` reads the interim asset (issuer = fighter_id, `QDOJOF`) instead of the bound one | **Detected.** At tick 1525 of `scenarios` a fighter bound by AdminBindAsset cannot register (NOT_OWNER where the port says OK); the digest mismatches. |

## Pinned qubic/core (e3ef766): what compiles

Core's GoogleTest build runs on Windows/MSVC only
(`.github/workflows/build-tests.yml`). Its clang port is marked
work-in-progress (`README_CLANG.md`: "not resulting in a working node";
only m256, math_lib and network_messages tests working).

On this host, with Core's own CMake flags and clang 18, the test translation
unit (`test/contract_qdojo.cpp` + `contract_testing.h` + all contracts)
stops at **324 errors, all inside Core**:

- MSVC intrinsics: `_InterlockedCompareExchange8`, `_umul128`, `__shiftright128`, …;
- `wchar_t` vs `CHAR16` string arrays;
- missing `typename` in `qpi_oracle_impl.h`;
- `four_q.h`, `file_io.h`, …

None of the 324 errors are in `QDOJO.h` or in the test. That is the full
extent of what the pinned Core can check on Linux. Core-lite exists to fix
exactly these portability errors, so the build and run happen there.

Warnings: QDOJO.h has 18, all `-Wunused-parameter` for the `qpi`, `input`,
`output` or `locals` parameters that the `PUBLIC_FUNCTION*` and
`*_WITH_LOCALS` macros generate. Core's own contracts produce the same class
of warning; for example, Nostromo.h has 87 and Pulse.h has 65.

## State size

| | Size |
|---|---:|
| `sizeof(QDOJO::StateData)` | 1,521,208 bytes (1485.6 KiB); 1,439,280 before the asset (issuer, name) was added to each registry entry |
| port's `sizeof(State)` | 1,485,224 bytes |

The difference has two causes:

- the retained event body is `Array<uint8,128>` instead of 112 bytes, because
  QPI Arrays must be 2^N long;
- `Array` alignment padding.

| Table | Records × size |
|---|---|
| fighters | 1024 × 496 |
| events | 2048 × 184 |
| accounts | 2048 × 96 |
| pairs | 4096 × 40 |
| assets | 2048 × 80 |
| cups | 8 × 5976 |
| offers | 128 × 296 |
| contests | 32 × 496 |
| fights | 32 × 296 |

## Commands

Everything is reproducible from the pinned commits:

```sh
# needs: git cmake ninja clang(>=18) nasm flex clang-tidy zlib1g-dev
#   (on this host: sudo apt-get install -y clang lld nasm flex clang-tidy)
make qubic-verify        # = python3 contracts/qubic/core_harness.py verify
make qubic-core-test     # = python3 contracts/qubic/core_harness.py test
make qubic-core-syntax   # = python3 contracts/qubic/core_harness.py core-syntax
python3 contracts/qubic/core_harness.py all --work /some/dir --jobs 1
```

The harness does the following:

1. **Verifier.**
   1. Fetches contract-verify at `970ce10` and CppParser at `3b5801f`.
   2. Builds both: `cmake -DCMAKE_BUILD_TYPE=Release ..; cmake --build . -j1`.
   3. Runs `build/src/contractverify contracts/qubic/QDOJO.h` and the six
      negative controls.
2. **core-lite test.**
   1. Fetches core-lite at `5ad97af`.
   2. Registers QDOJO in `src/contract_core/contract_def.h`, after QTREAT,
      keeping CRLF line endings, with the entry
      `{"QDOJO", 232, 10000, sizeof(QDOJO::StateData)}` (`CONSTRUCTION_EPOCH`) and
      `REGISTER_CONTRACT_FUNCTIONS_AND_PROCEDURES(QDOJO)`.
   3. Appends a `qdojo_core_tests` target to `test/CMakeLists.txt`. Its
      sources are `contract_qdojo.cpp`, `common_def.cpp` (Core globals) and
      `stdlib_impl.cpp`. It uses the core-lite test flags without `-w`, and
      it links `GTest::gtest_main`, `platform_common`, `platform_os` and
      `Blosc2::blosc2_static`.
   4. Copies `QDOJO.h` to `src/contracts/` and `test_qdojo_core.cpp` to
      `test/contract_qdojo.cpp`.
   5. Configures, builds and runs:

      ```
      cmake -S core-lite -B build-core-lite -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
            -DBUILD_TESTS=ON -DBUILD_BINARY=OFF -DANT_WALKER=OFF -DCMAKE_BUILD_TYPE=Release -DENABLE_AVX512=ON \
            -DUSE_SANITIZER=OFF -DQDOJO_PORT_DIR=<repo>/contracts/combat_contract
      ninja -j1 qdojo_core_tests
      QDOJO_JOURNAL_DIR=<repo>/packages/qdojo/tests/combat/fixtures/contract build-core-lite/test/qdojo_core_tests
      ```

      `USE_SANITIZER=OFF` matches core-lite's CI. With the alignment
      sanitizer on, a misaligned store in Core's own logging code
      (`src/logging/logging.h:411`) aborts the test run.
3. **Pinned core syntax.**
   1. Fetches core at `e3ef766` and registers QDOJO in the same way.
   2. Configures with `-DBUILD_EFI=OFF`.
   3. Runs the test translation unit's own compile command with
      `-fsyntax-only -ferror-limit=0 -Wno-error`, and counts errors by file.

## What remains

Status of the items in [`../combat_contract/README.md`, "What remains before
a real Core build"](../combat_contract/README.md#what-remains-before-a-real-core-build):

1. **Transliterate, verify, test in Core's harness.** Done. Core's own
   Windows/MSVC CI build and a multi-node testnet were not run.
2. **Nesting depth, locals under 32 KiB.** Done. No `CALL`s. Locals peak at
   29,208 bytes (`END_TICK`). That is within 3.5 KiB of the limit, so adding
   state to `Ctx` needs care; the NFT procedures below will need their own
   scratch budget.
3. **SHA-256 cost.** The wall time is measured above. The execution-fee model
   was not measured; it needs a node that charges fees.
4. **State digest cost.** Measured: about 1.4 ms K12 per tick, every tick.
   The mitigations in that list are still open:
   - smaller capacities or `EXPAND`;
   - a heartbeat that does not dirty state every tick.
5. **Asset ownership.** Done for the binding: AdminBindAsset (103) carries
   (issuer, name) and `ownerOf` reads that asset; the "unavailable" path is
   covered. Still open is the recommended NFT model, in which QDOJO issues and
   manages the assets itself (docs/nft.md §5.3; round-3 research against
   qubic/core `e3ef766`):
   - an issue procedure: `qpi.issueAsset(name, SELF, 0, 1, 0)` (issuer = the
     contract; no QX fee), then `qpi.transferShareOwnershipAndPossession` to
     the owner, and the binding in the 103 shape with issuer = the contract's
     identity;
   - the market of `nft.py` §3: asks, escrowed bids, fees, royalty, the
     contest lock and deferred settlement, with parity journals that carry
     `nft` records;
   - `PRE_ACQUIRE_SHARES` accepting assets QX releases back at fee 0, for
     QDOJO-issued assets only; `PRE_RELEASE_SHARES` refusing every pull;
   - an owner-invoked exit to QX (`qpi.releaseShares` to index 1, offered fee
     ≥ 100 QU) only while the fighter is IDLE;
   - the frozen-art anchor (bare CIDv1 references, the manifest root on chain).

   Meanwhile a QX-issued asset binds through 103 as it is (1,000,000,000 QU
   per issuance, also on testnet).
6. **Transfer semantics.**
   - Failure is a negative return value with no mutation (read in Core's
     source and exercised by the test).
   - The attachment is counted once.
   - Which real recipients can fail on mainnet, other than through
     insufficient balance, is still open. The test induces failure through
     the balance.
7. **Procedure and function IDs.** Frozen as the v1 ABI (`Dispatch` 1,
   queries 1–10). The contract index is assigned at registration.
8. **Tick successor across an epoch boundary.** Not tested. The harness never
   runs `BEGIN_EPOCH`/`END_EPOCH`, and no seamless epoch transition happens.
9. **NOT_DIRECT.** Not implemented, because semantics are kept identical.
10. **Frame truncation.** `Dispatch_input` is exactly 512 bytes, so Core pads
    or truncates. The test pads short journal frames the same way.

Other points:

- **Account lookups** are still linear over 2048 slots, not a `HashMap`. The
  port uses the same bounded table, which is what is proven equal. The cost
  shows up in `Dispatch` time, not in correctness.

## Done: AdminMirrorOwner (opcode 104) for the qbay-mirror backend

Ported on 2026-10-03 from the Python reference (`combat/contract.py`
`_op_admin_mirror_owner`, `_owner`, `_not_mirrored`; tests in
`tests/combat/test_qbay_mirror.py`) into `QDOJO.h` and the C++ port
(`contracts/combat_contract/combat_contract.h`), as the earlier specification
here laid out. [docs/nft.md](../../docs/nft.md) §5.4 explains the design and
[protocol.md](../../docs/protocol.md) §3 the frame.

- **Constants.** `QDOJO_OP_ADMIN_MIRROR_OWNER = 104`, `QDOJO_EV_OWNER_MIRRORED
  = 30`, `QDOJO_MIRROR_SOURCE_QBAY = 12` (the port: `OP_ADMIN_MIRROR_OWNER`,
  `EV_OWNER_MIRRORED`, `MIRROR_SOURCE_QBAY`).
- **State.** `RegistryAsset` gains `uint8 mirrored` (in the padding after
  `used`), `uint64 mirrorSeq` and `id mirrorOwner`: 80 → 120 bytes per entry,
  `sizeof(StateData)` 1,521,208 → 1,603,128. A mirrored entry's `issuer` is
  the source contract's identity (index 12, little-endian) and `assetName` the
  QBAY NFT id, so `bindAsset`'s existing (issuer, name) scan also refuses one
  NFT backing two fighters.
- **`ownerOf`.** A mirrored entry returns `mirrorOwner` and skips
  `AssetOwnershipIterator`; NULL_ID is "unavailable". Every caller already went
  through `ownerOf`.
- **`opAdminMirrorOwner`** checks, in reference order: an amount
  (BAD_AMOUNT); a non-admin (NOT_OWNER); `house_npc` > 1, a source other than
  12 or `mirror_seq` 0 (BAD_BODY); an existing mirrored entry with another
  (version, npc, source, id) (BAD_STATE) or a `mirror_seq` not above the
  stored one (STALE); an entry bound by 100/103 (BAD_STATE); otherwise binds
  through `bindAsset` (BAD_STATE, FULL). It stores owner and sequence and
  emits OWNER_MIRRORED (fighter_id, source_contract, source_id, owner,
  mirror_seq). Opcodes 100 and 103 refuse a mirrored entry with BAD_STATE.
- **Scratch.** `Ctx` grows by `h_src`, `h_sid`, `h_mowner`, `h_mseq` and the
  wider `h_asset`: 27,672 → 27,768 bytes; `END_TICK_locals` 29,208 → 29,304,
  still 3,464 bytes under the 32,768-byte limit.
- **Harness.** `test_qdojo_core.cpp`'s pre-scan binds no Core asset for a
  104-bound fighter, so the `owner` records a qbay-mirror world still writes
  move nothing (the contract reads `mirrorOwner`), and 100/103 on a mirrored
  fighter bind nothing. A call record may carry the reference's result code
  (`"code"`); `store.replay`, `test_contract.cpp` and `test_qdojo_core.cpp`
  then check it call by call, because result codes are not in the event
  digest.

| Journal | Written by | Covers |
|---|---|---|
| `mirror.journal` (candidate 3) | `scripts/combat-contract-mirror.py` | 104 binding two fighters and both owners registering; a ranked fight in which one owner is mirrored to a new identity mid-fight (the snapshot owner is paid); the old owner refused (NOT_OWNER) and the new one registering (`auth_version` 2); repeated and lower `mirror_seq` (STALE); a zero owner (BAD_STATE on SetOperator and QueueEnter), then the owner restored (DUPLICATE); a stranger and a slot-holding non-admin (NOT_OWNER), source 1, seq 0 and npc 2 (BAD_BODY), an attached amount (BAD_AMOUNT), a second fighter on one NFT, a re-pointed, re-versioned or re-npc'd fighter, 100 and 103 on a mirrored fighter and 104 on a 103-bound one (BAD_STATE). Every call carries its reference result code |
| `mirror-arena.journal` (candidate 3) | the same script | a real qbay-mirror arena (`live.Arena`, profile demo-c3, three bots) whose bridge reads the recorded mainnet answers of `tests/fixtures/qbay/mainnet.json` (no network): three fighters bound to BITE: Ocean Rebels NFTs, a QubicBay sale of NFT 5497 mirrored while the bots fight, NFT 5499 vanishing (zero owner, then BAD_STATE for its bot); 400 ticks, 128 calls, 5 AdminMirrorOwner |

Negative controls on the port (`test_contract_c3` on both journals): accepting
an equal `mirror_seq` (STALE check `<` instead of `<=`) and dropping the
mirrored check of opcode 100 both end at another digest; treating a zero
mirrored owner as available keeps the digest but fails `mirror.journal`'s
recorded result code at tick 309 (NOT_OWNER where the reference says
BAD_STATE).

## Local testnet (core-lite, step 4)

**The node was built and launched, but it cannot run a local testnet on this
7.9 GB host.**

**Build.** The node was built from the same core-lite checkout with QDOJO
registered and compiled in; the binary contains the `QDOJO` symbols.

```
sudo apt-get install -y libboost-dev          # boost/stacktrace headers, build dependency only
cmake -S core-lite -B build-node -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
      -DBUILD_BINARY=ON -DBUILD_TESTS=OFF -DTESTNET=ON -DTESTNET_LITE_RAM=ON -DANT_WALKER=OFF \
      -DCMAKE_BUILD_TYPE=Release -DUSE_SANITIZER=OFF -DENABLE_AVX512=ON
ninja -C build-node -j1 Qubic                 # 5 min 54 s, peak RSS 673 MB, OK (23.5 MB static binary)
```

**Launch.** The node was started inside a memory-capped user scope. The cap
keeps the host and the running validation campaign safe:

```
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  env PATH=/nonexistent build-node/src/Qubic --node-mode 3 --ticking-delay 1000
```

- `PATH` is emptied so that the crash reporter cannot `curl`
  api.qubic.global.
- The node only knows the TESTNET default peer, 127.0.0.1, and only the
  built-in test seeds.

The node printed:

- `This node is running as TESTNET`;
- `Operating with 676 computor seeds`;
- `MAIN&MAIN mode enabled`;
- `Qubic 1.305.0 is launched`;
- its own RAM accounting: `Total RAM required 12 GB`.

The largest items in that accounting:

| Item | Size |
|---|---:|
| `contractStates_sum` (every contract's state; QDOJO is 1.4 MB of it) | 5050 MB |
| `score+score_qpi` | 2105 MB |
| `commonBuffers` | 2048 MB |
| `peer_buffers` | 960 MB |
| `processor_buffers` | 720 MB |
| `ocEngine` | 701 MB |

About 10 s after launch it hit the 3 GB cgroup cap: peak 2.8–3.1 GB, and
systemd reported `Result=oom-kill`. It was killed inside its own scope. No
tick was processed.

**Why it cannot run here.** The host has 7.9 GB, about 5.6 GB of which is
available while the validation campaign runs. The node itself reports
12 GB. core-lite's README says "~7 GB" for `TESTNET_LITE_RAM`, but this
build reports 12 GB.

A run with a larger cap was not attempted, because it would starve the
running validation campaign.

**Construction epoch.** That run registered QDOJO with construction epoch
240 while the testnet starts at `EPOCH 232`, so even a node with enough RAM
would not have constructed it. Since 2026-09-30 the harness registers it at
232. What a real local testnet run still needs:

- a machine with at least 12 GB free (core-lite's README says 16 GB);
- the node built as above from a checkout the harness has registered
  (`python3 contracts/qubic/core_harness.py test --work DIR` registers QDOJO
  in `DIR/core-lite`), then `Qubic --node-mode 3 --ticking-delay 1000` under
  a memory cap, with `PATH` emptied;
- a release-shaped manifest in `loadDefaultManifest` (real identities, the
  testnet `network_id`), and seeds for the admin and the bots
  (docs/testnet.md §3.3), because the compiled profile's admin is a synthetic
  test key with no seed.
