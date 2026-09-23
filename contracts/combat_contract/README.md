# combat_contract: C++ port of the reference combat contract

This is package P7 of [docs/pivot-plan.md](../../docs/pivot-plan.md). It ports the validated
Python reference contract to C++ in the shape a Qubic smart contract needs,
and it proves parity by replaying the reference's input journals.

| File | Contents | Status |
|---|---|---|
| `combat_contract.h` | The pure state machine: `State`, `init`, `begin_tick`, `dispatch`, `end_tick`, `query_*`. The host interface (`Host::owner_of`, `Host::transfer`) is abstract. | Compiled with `-Wall -Wextra -Werror -Wconversion -fno-exceptions -fno-rtti -nostdinc++`. Parity-tested. |
| `qpi_adapter.h` | QPI-shaped sketch: `struct QDOJO : ContractBase`, `StateData`, `Dispatch(Array<uint8,512>)`, `BEGIN_TICK`/`END_TICK`, `OwnerOf`, `PayOut`, query functions, `REGISTER_USER_FUNCTIONS_AND_PROCEDURES`. | **Not compiled. Not run through the contract verifier.** Written against the pinned Core below. |
| `test_contract.cpp` | Parity runner. It has a hand-rolled JSON-lines parser, a fake chain host, journal replay, the final-digest check, a ledger conservation check after every step, and state-size and work reports. | This is the only file that uses the standard library. |

The port reuses `../combat_core/combat_core.h` (the engine) and
`../combat_core/sha256.h` (SHA-256 and the context, round-state and
commitment digests) without changes.

## What is ported

The following reference code is ported, from `packages/qdojo/src/qdojo/combat/`:

- `contract.py`: the whole state machine. This covers:
  - the service heartbeat and generations;
  - nonces and identical retries;
  - refunds;
  - the registry, operators and locks;
  - the ranked queue and matching;
  - duels;
  - commit and reveal;
  - deadlines;
  - series;
  - settlement;
  - faults and cooldown;
  - ratings and season stats;
  - cups (bracket, byes, check-in, postponement, replay, prize, aborts);
  - admin opcodes 100–102;
  - the event ring and append digest;
  - season standings.
- `ledger.py`: the buckets, `split_purse` and the cup prize. Credits live in the account table.
- `matchmaking.py`: the window, the `compatible` predicate and `matching_pass`, with the same bounds (64 snapshot, 4 matches).
- `series.py`: formats, replay series, `seed_positions` and `bracket`.
- `rating.py`: `delta` and `update`, integer only.
- `codec.py`: the strict 512-byte frame decode, body layouts, result codes, the plan shape check and `event_digest`.
  Event bodies follow `contract.py _event_body` (tag 0 u64, tag 1 u16-length bytes, tag 2 u8-length ASCII) with the `EVENT_TYPES` numbers.

## Capacities and state size

The capacities are compiled in. The manifest's runtime values must be less
than or equal to them, and `init` rejects a manifest that is not.

| Record | Capacity | Notes |
|---|---:|---|
| fighters | 1024 | Never evicted. The index is the stable fighter handle. |
| accounts | 2048 | One entry per identity: the account slot (`contract.py self.accounts`: nonce and credit), bounded by the manifest's `max_accounts`. Slots are seeded with the admin and the fee recipients and are never released. |
| registry assets | 2048 | Written by admin opcode 100. |
| open offers | 64 | 128 slots. Terminal offers are evicted, lowest id first. |
| active fights | 16 | 32 slots. Terminal fights are evicted. |
| contests | 16 active | 32 slots. Terminal, settled contests are evicted. |
| cups | 4 live × 16 entrants | 8 slots and 15 pairings each. Terminal cups are evicted. |
| ranked pair history | 4096 | Open addressing. Stale entries are reused. |
| event ring | 2048 | Bodies are kept up to 112 bytes. The largest canonical body, REVEALED, is 98 bytes. |

`sizeof(State)` is **1,403,296 bytes (1370.4 KiB)**:

| Table | Size |
|---|---|
| fighters | 1024 × 496 = 496 KiB |
| events | 2048 × 168 = 336 KiB |
| accounts | 2048 × 96 = 192 KiB |
| pairs | 4096 × 40 = 160 KiB |
| assets | 2048 × 40 = 80 KiB |
| cups | 8 × 5832 = 46 KiB |
| offers | 128 × 288 = 36 KiB |
| contests | 32 × 472 = 15 KiB |
| fights | 32 × 288 = 9 KiB |

Each fighter keeps two season slots, current and previous. Each slot has a
1024-bit "defeated" bitmap because the standings tiebreak needs the exact
number of distinct defeated opponents.

## Parity

`make contract-test` runs the following steps:

1. Checks the header with the strict flags.
2. Builds the runner.
3. Replays every file in `packages/qdojo/tests/combat/fixtures/contract/*.journal`.

For each journal the replay must end at the reference's recorded final event
digest. The digest chains every canonical event body, so a match means every
event, field, order and value agrees with the reference. After every journal
step the runner also asserts two things:

- `balance == sum(liabilities)` and no credit is negative;
- every fault counter is zero: arithmetic, account, pair, slot and engine.

| Journal | Records | Calls | END_TICKs | Events | Result |
|---|---:|---:|---:|---:|---|
| fuzz-1 | 3253 | 1203 | 2000 | 1332 | final digest identical |
| fuzz-2 | 3300 | 1253 | 2000 | 1427 | final digest identical |
| season | 11206 | 516 | 10675 | 901 | final digest identical |
| scenarios | 1889 | 277 | 1534 | 420 | final digest identical |

`--trace DIR` writes one line per event (`E seq tick type body digest`) and one
line per call (`C tick code op target refunded`). The format matches a
reference-side dump. On all four journals the port's trace equals the
reference's line for line, so result codes, targets and refunds also agree.
Result codes are not part of the digest.

`scenarios.journal` (358 KB) is written by `scripts/combat-contract-scenarios.py`,
which `scripts/combat-sample-data.py` runs. It is a scripted run with a short
timing profile (commit 4, reveal 3), 4 fight slots and 48 account slots, and
salts from a seeded RNG, so regeneration is byte-identical. It covers:

- a ranked match with rating, a failed then retried withdrawal, and SetOperator at IDLE;
- Advance with a nonzero nonce, and AdminCreateCup rejections;
- a cup with three byes, a drawn pairing replayed, one fighter per owner, a
  withdrawn entry, SetOperator refused after check-in and allowed between
  pairings, and a finalist sold during the final;
- a postponed level whose retry succeeds, then NO_CHAMPION;
- a level postponed twice (CAPACITY), with a duel accept refused FULL;
- a cup CANCELLED below minimum;
- a service gap voiding a duel, an open offer and a cup (SERVICE_VOID);
- ruleset retirement;
- strangers refused NOT_OWNER, refunds taking the last account slots, a new
  registrant refused FULL, and direct paybacks, one of which fails.

Together the four journals emit all 29 event types. Two cup fuzz runs of 9,000
ticks each (16 MB, not committed) also replay with identical traces.

Two paths cannot be reached, so no journal covers them:

- **EXPIRED cup abort.** Every level now finishes inside its window, because
  descriptor validation guarantees the worst case fits. The expiry is a full
  window beyond the last permitted final.
- **Check-in COOLDOWN.** A fighter can only fault while it is locked in the
  cup, and a fault (forfeit or double fault) eliminates it. CupRegister
  already refuses a fighter in cooldown.

Maximum work per entry point seen over these journals:

| Entry point | SHA-256 blocks | Events | Fights advanced | Match comparisons | Owner queries | Transfers |
|---|---:|---:|---:|---:|---:|---:|
| dispatch | 24 | 2 | 0 | 0 | 2 | 1 |
| end_tick | 45 | 8 | 4 | 10 | 6 | 0 |

Linear lookups visit up to about 6,200 table slots per entry point, mostly the
2048-slot account table. On chain these lookups belong in `HashMap`. The
analytical worst case for END_TICK is 16 fights resolving and starting their
next fight, plus 4 matches and 4 cup ticks. That comes to about 600 SHA-256
blocks, which is well below any per-tick budget still to be measured.

## Where the port must bound what the reference does not

The reference keeps every record forever. The port bounds everything, and it
never evicts anything that holds a liability or a lock. Account slots follow
the reference exactly (eligibility, `_claim`, FULL at `max_accounts`); only
the table size itself is a port bound. None of the rules below is reached by
the parity journals, except the terminal-id answers.

- **Terminal records are evicted, lowest id first.** An id that was issued
  (`1 <= id < next`) but is no longer retained must have been terminal, so
  the port answers the way the reference does for a terminal record:
  - Advance returns OK;
  - Commit and Reveal return TERMINAL;
  - cup operations return WRONG_PHASE.

  One case remains open. QueueCancel, DuelCancel and DuelAccept on an evicted
  offer return NOT_FOUND. The reference would answer DUPLICATE,
  ALREADY_MATCHED or EXPIRED. DUPLICATE is the only accepted answer of the
  three, so the difference is whether that nonce is recorded.
- **Credits with no free table entry go to `overflow_credit`.** The credit
  stays a liability and a fault counter is incremented. This can only happen
  for credit-only entries: failed direct paybacks to identities without a
  slot, which the reference records without a slot.
- **Pair history keeps only what matching can still read:** current-epoch
  start counts and results less than 120 ticks old. If the table is full, a
  pair is treated as not matchable, which fails closed.
- **Season data covers the current and the previous season.** Standings for
  older seasons belong to the exported history.
- **The asset registry holds 2048 entries.** A further registration is
  refused with FULL.

## What remains before a real Core build

1. **Transliterate into the QPI dialect and compile inside Core.** Core's
   contract rules forbid `#include`, pointers, `[ ]`, `/`, `%`, string and
   char literals, stack locals, globals and `...`. `combat_contract.h`
   uses all of them, so it is a reference for a mechanical translation and
   is not itself the contract source. `qpi_adapter.h` lists the rules and
   the shape. After translation:
   - run the qubic/contract-verify tool;
   - add `test/contract_qdojo.cpp` in Core's GoogleTest harness;
   - replay these journals there.
2. **Nesting depth.** Core allows at most 10 nested contract calls. The
   deepest reference path is exactly 10 deep:
   END_TICK → fight_tick → resolve → end_fight → finish_contest →
   cup_pairing_done → pairing_event → emit → sha update → compress.
   Flatten `emit` and SHA-256 first. Also check that each procedure's
   locals stay under 32 KiB.
3. **SHA-256 cost inside QPI.** QPI provides only K12, and the protocol
   forbids substituting it. The SHA-256 helper must be transliterated and
   then benchmarked under the execution-fee model (up to about 600 blocks
   per worst-case tick).
4. **State digest cost.** END_TICK writes `last_serviced` every tick, so
   Core rehashes the whole state every tick. For a 1.37 MB state this is
   probably the dominant recurring cost. Measure it, then consider:
   - smaller capacities, grown later with `EXPAND`;
   - trimming the event ring and the season bitmaps;
   - a heartbeat design that does not need to write state every tick.
5. **Asset ownership.** The spec maps a fighter to one indivisible Qubic
   asset (issuer and name). AdminRegisterAsset (opcode 100) carries neither,
   so the adapter's `OwnerOf` has nothing to iterate over. The descriptor
   must gain the issuance. After that, test ownership against possession
   and against managing-contract rights.
6. **Transfer semantics.** `qpi.transfer` returns the remaining balance, or
   a negative value on failure. Still to prove on the pinned Core:
   - which recipients can fail;
   - that a failure mutates nothing;
   - how an incoming attachment interacts with `POST_INCOMING_TRANSFER`. It
     must be counted once.
7. **Procedure and function IDs.** The IDs in the adapter are placeholders.
   The real numbers are deployment values from the release manifest.
8. **The tick successor across an epoch boundary.** The first tick of a new
   epoch is `initialTick`, which is not necessarily the previous tick plus
   one. If it is not, the heartbeat opens a SERVICE_GAP every epoch and
   voids live contests. This must be pinned and tested; protocol.md section 5
   already blocks paid activation until it is.
9. **Direct callers.** Protocol.md section 1 requires `invocator ==
   originator` for fighter actions. The reference has no notion of a
   calling contract. The adapter proposes rejecting nested calls with a new
   code, NOT_DIRECT, which the reference and the protocol code list must
   first adopt.
10. **Frame truncation.** Core pads or truncates the input to
    `sizeof(Dispatch_input)` (512 bytes). The reference rejects any frame
    that is not 512 bytes. On chain, only the interpreted 512 bytes exist.

## Core commit read

The Core commit read is qubic/core `e3ef766686e5d69a2bdd17a12213f1d21d145778`,
dated 2026-09-23. The following files were read:

- `doc/contracts.md`;
- `src/qpi/{qpi.h, qpi_types.h, qpi_context.h, qpi_assets.h, qpi_containers.h, qpi_macros.h}`;
- `src/platform/m256.h`;
- the tick callbacks in `src/qubic.cpp`;
- `src/contracts/{EmptyTemplate, QDuel, Pulse, Qswap}.h`, for idioms.

Nothing from Core was compiled.

## Run

```sh
make contract-test                         # header check, build, replay the committed journals
contracts/combat_contract/test_contract --trace /tmp/out J.journal   # per-event trace for diffing
```
