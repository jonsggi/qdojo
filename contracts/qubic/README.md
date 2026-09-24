# contracts/qubic: QDOJO in the Qubic Core contract dialect

This is package P7 of [docs/pivot-plan.md](../../docs/pivot-plan.md), step
"transliterate into the QPI dialect and prove it inside Core". It turns the
parity-tested bounded port [`../combat_contract/combat_contract.h`](../combat_contract/combat_contract.h)
into a real Qubic Core contract, and checks it with Qubic's own tooling as far
as this host allows.

| File | Contents |
|---|---|
| `QDOJO.h` | The contract, in Core's restricted C++ dialect. It has one `Dispatch` user procedure taking `Array<uint8,512>`, `INITIALIZE`, `BEGIN_TICK`, `END_TICK`, and ten bounded query functions. SHA-256 is implemented inside the contract. |
| `test_qdojo_core.cpp` | A GoogleTest for Core's contract test harness (`test/contract_testing.h`). It replays every reference journal through the QPI-built contract. Install it as `test/contract_qdojo.cpp`. |
| `core_harness.py` | Reproduces every check below from pinned upstream commits: `verify`, `test`, `core-syntax`, `all`. |

Summary. Commit and tool versions are in [Pins](#pins).

| Check | Tool | Result |
|---|---|---|
| Dialect compliance | qubic/contract-verify, the SHA that Core's CI pins | **PASSED**. Six injected violations are all rejected, so the tool really parses the whole file. |
| Compiles inside Core's test harness | core-lite (the Linux/clang port of Core), clang 18 | **Yes.** QDOJO.h has no errors and 18 warnings, all `-Wunused-parameter` from the QPI macros. |
| Journal replay through the real contract | core-lite GoogleTest `qdojo_core_tests` | **All 4 journals end at the reference's final event digest.** The call results and the event digest also match the C++ port after every step. |
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

## Deviations the chain forces (behaviour otherwise identical)

- **The manifest is compiled in.**
  - `INITIALIZE` loads a TEST PROFILE (`loadDefaultManifest`). This is the
    fuzz journal's header: its synthetic test identities, and
    `contractId = SELF`. It is not a release manifest.
  - The pair limits `pairStartsPerEpoch` and `pairRematchTicks` are manifest
    fields. The compiled profile uses the specified 2 and 120
    (`QDOJO_PAIR_STARTS_PER_EPOCH`, `QDOJO_PAIR_REMATCH_TICKS`). The harness
    loads them from each journal header, so `demo-profile.journal` (6 and 60)
    also replays.
  - A test may write `StateData::m` and set `manifestLoaded` before
    `INITIALIZE`. On chain the state arrives zeroed, so the compiled profile
    is always used.
  - The checks in `init` are unchanged. A failing manifest leaves
    `initOk = 0`. Every entry point is then inert, and `Dispatch` hands the
    attachment straight back.
- **`Host::owner_of` becomes `ownerOf`.**
  - It reads the single owner (shares > 0) of the asset whose issuer is
    `fighter_id` and whose name is `QDOJOF`, through
    `AssetOwnershipIterator`.
  - No record, several owners, or a NULL_ID owner means "unavailable".
  - This is an interim binding. `AdminRegisterAsset` still carries no
    issuance; that is the protocol gap listed in the port README, item 5.
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

  `Dispatch` is user procedure 1. All IDs are placeholders. The real numbers
  are deployment values.

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
| `owner` | Issues the one-unit `QDOJOF` asset once with the fighter id as issuer, then moves ownership and possession with Core's `transferShareOwnershipAndPossession`. |
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

Result on this host (`qdojo_core_tests`, Release, core-lite 5ad97af, clang 18):

```
[ RUN      ] ContractQdojo.StateAndLocalsSizes
sizeof(QDOJO::StateData) = 1439280 bytes (1405.5 KiB); MAX_CONTRACT_STATE_SIZE = 1073741824
  fighters 1024 x 496, assets 2048 x 40, accounts 2048 x 96, events 2048 x 184, pairs 4096 x 40
  offers 128 x 296, contests 32 x 496, fights 32 x 296, cups 8 x 5976
locals: Ctx 27576, Dispatch 27624, END_TICK 29112, BEGIN_TICK 27576, INITIALIZE 27576 (limit 32768)
K12 over 1439280 state bytes: 1425.4 us per digest (this host, 20 reps)
[ RUN      ] ContractQdojo.InitializeWithCompiledManifest               OK
[ RUN      ] ContractQdojo.ReplayScenarios
scenarios.journal: 1912 records, 300 calls, 1534 END_TICKs, 442 events, balance 49609 QU; codes 0x283 2x3 4x4 7x3 10x1 12x2 18x2 19x1 29x1
    final event digest b803e6c26f5f30c5f9ee5bbb5ffeaf36b3f84b34d9e7668ae29d8142bb6166a0 (reference b803e6c2…6166a0) MATCH
[ RUN      ] ContractQdojo.ReplayFuzz1
fuzz-1.journal: 3253 records, 1203 calls, 2000 END_TICKs, 1332 events, balance 81765 QU; codes 0x889 2x86 11x207 18x17 24x4
    final event digest 8738c597e78ac5fc1704f8ab2c6f4de9ada42ae340947383624b6e99591daaca (reference 8738c597…1daaca) MATCH
[ RUN      ] ContractQdojo.ReplayFuzz2
fuzz-2.journal: 3300 records, 1253 calls, 2000 END_TICKs, 1427 events, balance 62662 QU; codes 0x994 2x93 11x145 18x14 24x7
    final event digest 4cc7979d2b53405752e199996cc7e3a5ed526b5967172ffaa74181f98da26318 (reference 4cc7979d…da26318) MATCH
[ RUN      ] ContractQdojo.ReplaySeason
season.journal: 11206 records, 516 calls, 10675 END_TICKs, 901 events, balance 251000 QU; codes 0x516
    final event digest 20bff91896fe40971aa1c81e98b2d7ce6ad8d58bb201e4e12f5f581c64330f47 (reference 20bff918…64330f47) MATCH
[  PASSED  ] 6 tests.
Maximum resident set size: 2.1 GB (Core's test spectrum + universe); build of the test TU: 27 s, 336 MB
```

In the scenarios journal, code 29 is `TRANSFER_FAILED`. That result is
Core's real `qpi.transfer` failing: a withdrawal fails, then is retried.

The failed direct payback in the same journal also goes through Core. The
`REFUND_CREDIT` event and the digest match.

`core_harness.py all --jobs 1` reproduced every result in this section from fresh
shallow clones of the pinned commits: the verifier, the four digest matches, and
the pinned-core syntax check.

Time spent in the contract, measured around Core's call wrappers on this host
(AVX-512, Release, one run, with other jobs on the machine). The averages are
stable between runs. The maxima are noisy: in the harness rerun, the
scenarios Dispatch max was 753 µs.

| Journal | Dispatch avg | Dispatch max | END_TICK avg | END_TICK max |
|---|---:|---:|---:|---:|
| scenarios | 14.7 µs | 447 µs | 2.0 µs | 614 µs |
| fuzz-1 | 9.8 µs | 72 µs | 1.7 µs | 48 µs |
| fuzz-2 | 10.4 µs | 203 µs | 1.7 µs | 26 µs |
| season | 10.0 µs | 44 µs | 1.3 µs | 2033 µs |

Core then rehashes the dirty state with K12, and QDOJO dirties it every tick.
This takes about **1.4 ms per tick** for the 1.44 MB state, which is about
1000× the average END_TICK. That confirms the port README's item 4: the state
digest is the dominant recurring cost.

### Negative controls for the replay

A deliberately broken QDOJO.h was built into the same harness to see whether
the replay catches it.

| Mutation | Result |
|---|---|
| JAB vs RECOVER deals 13 damage instead of 12 | **Detected.** fuzz-1 diverges from the port at tick 52. The first diverging event is `ROUND_RESOLVED`, the next call's result differs, and the final digest mismatches. |
| `scheduleLevel` does not store the cup before `fightsInUse` | **Not detected**, and it cannot be. When a level is scheduled, the stale state copy holds the same reservation (0) and the same counted status, because every pairing has decremented `reserved` before `advanceLevel`. The store is kept as a safe aliasing rule. |
| `ownerOf` treats a NULL_ID owner as available | **Not detected.** No committed journal contains an `owner: null` record, so the "owner unavailable" path (`BAD_STATE` in `authorize`) is **not covered by any journal**, in the port or here. |

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
| `sizeof(QDOJO::StateData)` | 1,439,280 bytes (1405.5 KiB) |
| port's `sizeof(State)` | 1,403,296 bytes |

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
| assets | 2048 × 40 |
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
      `{"QDOJO", 240, 10000, sizeof(QDOJO::StateData)}` and
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
   29,112 bytes (`END_TICK`). That is within 3.6 KiB of the limit, so adding
   state to `Ctx` needs care.
3. **SHA-256 cost.** The wall time is measured above. The execution-fee model
   was not measured; it needs a node that charges fees.
4. **State digest cost.** Measured: about 1.4 ms K12 per tick, every tick.
   The mitigations in that list are still open:
   - smaller capacities or `EXPAND`;
   - a heartbeat that does not dirty state every tick.
5. **Asset ownership.** The interim binding is issuer = fighter_id, name
   `QDOJOF`. The descriptor still lacks the issuance. The NULL_ID
   ("unavailable") path is untested by the journals.
6. **Transfer semantics.**
   - Failure is a negative return value with no mutation (read in Core's
     source and exercised by the test).
   - The attachment is counted once.
   - Which real recipients can fail on mainnet, other than through
     insufficient balance, is still open. The test induces failure through
     the balance.
7. **Procedure and function IDs.** Still placeholders.
8. **Tick successor across an epoch boundary.** Not tested. The harness never
   runs `BEGIN_EPOCH`/`END_EPOCH`, and no seamless epoch transition happens.
9. **NOT_DIRECT.** Not implemented, because semantics are kept identical.
10. **Frame truncation.** `Dispatch_input` is exactly 512 bytes, so Core pads
    or truncates. The test pads short journal frames the same way.

Other points:

- **Account lookups** are still linear over 2048 slots, not a `HashMap`. The
  port uses the same bounded table, which is what is proven equal. The cost
  shows up in `Dispatch` time, not in correctness.

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

**QDOJO would not have run anyway.** QDOJO is registered with construction
epoch 240, and the testnet starts at `EPOCH 232`. So even a node with enough
RAM would not construct it this epoch. A real testnet run needs:

- the construction epoch set to the testnet epoch;
- a machine with at least 12 GB free.
