# combat_core: C++ pure core of combat-v1

An independent C++ implementation of the qdojo combat-v1 engine
([docs/combat.md](../../docs/combat.md) §2–§7) and the commitment hashing
of [docs/protocol.md](../../docs/protocol.md) §2. It was written from the
spec, not ported from the Python engine. It is the starting point for the
Qubic smart contract.

| File | Contents |
|---|---|
| `combat_core.h` | ruleset constants, `Fighter`/`Plan`/`FightState`, `validate_plan`, `resolve_beat` (per-side trace plus a reason bitmask), `resolve_round`, `apply_break_recovery`, 8-byte state and 7-byte plan codecs |
| `sha256.h` | bounded SHA-256, `context_digest`, `round_state_digest`, `commitment` |
| `test_combat_core.cpp` | test runner. This is the only file that uses the standard library. |

## Constraints followed for the Qubic port

- Header-only, with no heap allocation, exceptions, RTTI, STL or includes beyond `<stdint.h>`.
- No floating point, RNG or clock. The code uses fixed-width integers only.
- Every loop has a fixed bound: 6 beats, 64 SHA rounds, or the input length.
  All hashed inputs have fixed sizes (context 526 B, commitment preimage 267 B).
- Constants are compiled in because a contract cannot parse JSON. The tests check two things:
  - every constant equals `docs/combat-v1.json`;
  - the canonical JSON of that file hashes to the embedded `RULESET_DIGEST`.
- Invalid input is rejected with an `Error` code and never clamped into shape.
  This covers an impossible state, a terminal fight, a bad plan and a noncanonical state encoding.
- The reason bits are stable (see the header comment) and descriptive only.
  No rule reads them.

When porting, replace `uint*_t` with the QPI types and move the fixed arrays
into contract state or locals. Keep the logic unchanged, then rerun this suite
against the same fixtures.

## Run

```sh
make cpp-test     # header check (-fno-exceptions -fno-rtti -nostdinc++) + build + run
make test         # also runs cpp-test when g++ is installed
```

The runner checks the following:

- every hand vector in combat.md §8;
- the NIST SHA-256 vectors: "", "abc", 448-bit, 896-bit and 1,000,000 × 'a';
- the frozen `docs/fixtures/commitment-v1.json`;
- a replay of every fight in `packages/qdojo/tests/combat/fixtures/fights-*.json`:
  - per-round 16-byte end states, executed beat counts and outcomes;
  - per-beat after-state, effective action, cost_paid, base, dealt, lost, strain and recovered for the traced fights.

Reason codes are compared against Python only for information and are not asserted.
Any mismatch makes the runner exit nonzero.
