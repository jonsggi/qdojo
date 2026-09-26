# combat_core: C++ pure core of combat-v1

An independent C++ implementation of the qdojo combat-v1 engine
([docs/combat.md](../../docs/combat.md) §2–§7) and the commitment hashing
of [docs/protocol.md](../../docs/protocol.md) §2. It was written from the
spec, not ported from the Python engine. It is the starting point for the
Qubic smart contract.

| File | Contents |
|---|---|
| `combat_core.h` | ruleset tables (candidate 1 and candidate 2, one selected per build), `Fighter`/`Plan`/`FightState`, `validate_plan`, `resolve_beat` (per-side trace plus a reason bitmask), `resolve_round`, `apply_break_recovery`, 8-byte state and 7-byte plan codecs |
| `sha256.h` | bounded SHA-256, `context_digest`, `round_state_digest`, `commitment` |
| `test_combat_core.cpp` | test runner. This is the only file that uses the standard library. |

## Constraints followed for the Qubic port

- Header-only, with no heap allocation, exceptions, RTTI, STL or includes beyond `<stdint.h>`.
- No floating point, RNG or clock. The code uses fixed-width integers only.
- Every loop has a fixed bound: 6 beats, 64 SHA rounds, or the input length.
  All hashed inputs have fixed sizes (context 526 B, commitment preimage 267 B).
- Constants are compiled in because a contract cannot parse JSON. Every packaged
  ruleset is a `RulesetTable` (`CANDIDATE_1`, `CANDIDATE_2`), and a build selects
  one with `-DQDOJO_RULESET=1|2` (default 1). The engine reads the selected table
  through the same constant names (`DAMAGE`, `BASE_COSTS`, `RULESET_DIGEST`, ...),
  so the contract port is unchanged and a deployed contract serves exactly the
  ruleset its manifest names. A compile-time choice keeps every loop bound and
  array size constant and costs no contract state; a table indexed by digest at
  run time would have put a ruleset reference through every engine call for a
  contract that can only ever admit one digest. The tests check, in every build:
  - every constant of both tables equals `docs/combat-v1.json` and
    `docs/combat-v1-candidate-2.json`;
  - the canonical JSON of each file hashes to its table's digest.
- `contracts/qubic/QDOJO.h` still embeds candidate 1 only; a Qubic deployment
  on candidate 2 must regenerate its constants from the candidate 2 table.
- Invalid input is rejected with an `Error` code and never clamped into shape.
  This covers an impossible state, a terminal fight, a bad plan and a noncanonical state encoding.
- The reason bits are stable (see the header comment) and descriptive only.
  No rule reads them.

When porting, replace `uint*_t` with the QPI types and move the fixed arrays
into contract state or locals. Keep the logic unchanged, then rerun this suite
against the same fixtures.

## Run

```sh
make cpp-test     # header check (-fno-exceptions -fno-rtti -nostdinc++), build + run, for both rulesets
make test         # also runs cpp-test when g++ is installed
```

The runner checks the following:

- every hand vector of the selected ruleset (combat.md §8, or §11.3 for candidate 2);
- the NIST SHA-256 vectors: "", "abc", 448-bit, 896-bit and 1,000,000 × 'a';
- the frozen `docs/fixtures/commitment-v1.json`;
- a replay of every fight in the `packages/qdojo/tests/combat/fixtures/fights-*.json` file of the selected ruleset (the other is skipped):
  - per-round 16-byte end states, executed beat counts and outcomes;
  - per-beat after-state, effective action, cost_paid, base, dealt, lost, strain and recovered for the traced fights.

Reason codes are compared against Python only for information and are not asserted.
Any mismatch makes the runner exit nonzero.
