# qdojo wire protocol v0

All dojo messages are the `input` payload of an ordinary Qubic transaction
whose destination is the house identity, with `inputType = 0x444F`
(17487). The payload is at most 1024 bytes. Integers are little-endian.

```
header   "DOJO" (4 bytes)  version u8 = 0  kind u8
```

| kind | name | sender | body |
|---|---|---|---|
| 1 | BOW | bot | `name_len u8`, `name` utf-8 (≤ 32 bytes) |
| 2 | PUBLISH | house | `round_id u32`, `entry_fee u64`, `commit_window u16`, `reveal_window u16`, `riddle_hash 32`, `answer_commitment 32`, `uri_len u8`, `uri` |
| 3 | COMMIT | bot | `round_id u32`, `commitment 32` |
| 4 | REVEAL | bot | `round_id u32`, `salt 16`, `answer_len u16`, `answer` utf-8 (≤ 512 bytes) |
| 5 | SETTLE | house | `round_id u32`, `dojo_salt 16`, `settlement_hash 32`, `uri_len u8`, `uri` |

The house publishes PUBLISH and SETTLE to its own identity, so a single
address filter finds every dojo message of every round.

## Hashes

```
riddle_hash        = SHA256("qdojo/riddle/v0"  || canonical_json(public fields))
answer_commitment  = SHA256("qdojo/answer/v0"  || round_id u32 || dojo_salt 16 || canonical_answer)
commitment         = SHA256("qdojo/commit/v0"  || round_id u32 || identity ascii 60 || salt 16 || canonical_answer)
settlement_hash    = SHA256("qdojo/settlement/v0" || canonical_json(settlement without "hash", "settle_tx", "settle_tick"))
```

`canonical_json` is `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` encoded as UTF-8.

## Solver interface

A solver is any executable. The bot writes the riddle JSON to its stdin and
reads one JSON object from its stdout: `{"answer": <string or integer>}`.
Anything else, or a timeout, is "no answer" and the bot does not commit.

## Board

The house serves `board.json`:

```json
{"house": "<identity>", "generated_tick": 123, "rounds": [
  {"round_id": 1, "state": "commit", "publish_tick": 100, "publish_tx": "...",
   "entry_fee": 1000, "commit_window": 600, "reveal_window": 300,
   "riddle_hash": "<hex>", "answer_commitment": "<hex>", "riddle": {...}}
]}
```

A bot verifies `riddle_hash` against the embedded riddle before solving and
may verify the PUBLISH transaction on chain.
