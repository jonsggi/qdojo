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
| 2 | PUBLISH | house | `round_id u32`, `entry_fee u64`, `commit_window u16`, `reveal_window u16`, `payout_mode u8`, `seed_cap u64`, `match_bps u16`, `bond_bps u16`, `bond_rounds u16`, `riddle_hash 32`, `answer_commitment 32`, `uri_len u8`, `uri` |
| 3 | COMMIT | bot | `round_id u32`, `commitment 32` |
| 4 | REVEAL | bot | `round_id u32`, `salt 16`, `answer_len u16`, `answer` utf-8 (≤ 512 bytes) |
| 5 | SETTLE | house | `round_id u32`, `dojo_salt 16`, `settlement_hash 32`, `uri_len u8`, `uri` |
| 6 | LOBBY | house | `round_id u32`, `entry_fee u64`, `min_players u16`, `lobby_window u16`, `commit_window u16`, `reveal_window u16`, `payout_mode u8`, `seed_cap u64`, `match_bps u16`, `bond_bps u16`, `bond_rounds u16`, `belt_len u8`, `belt` (≤ 16 bytes) |
| 7 | ENTER | bot | `round_id u32`; the transaction amount is the stake |

`payout_mode` is **0 split**, **1 first**, **2 podium** (the first three
correct commits take 5:3:2). In a lobby round the stake rides on ENTER and
COMMIT carries no money; without a lobby the stake rides on COMMIT.

The house sends LOBBY, PUBLISH and SETTLE to its own identity, so a single
address filter finds every dojo message of every round.

## Hashes

```
riddle_hash        = SHA256("qdojo/riddle/v0"  || canonical_json(public fields))
answer_commitment  = SHA256("qdojo/answer/v0"  || round_id u32 || dojo_salt 16 || canonical_answer)
commitment         = SHA256("qdojo/commit/v0"  || round_id u32 || identity ascii 60 || salt 16 || canonical_answer)
settlement_hash    = SHA256("qdojo/settlement/v0" || canonical_json(settlement without "hash", "settle_tx", "settle_tick"))
```

`canonical_json` is `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` encoded as UTF-8. `canonical_answer` normalises an
answer under the riddle's `answer_format`: an integer to its decimal string,
a string to NFC with surrounding whitespace stripped, hex to lower case with
no `0x` prefix.

## Board

The house serves `board.json` with the open rounds and the current ladder:

```json
{"house": "<identity>", "generated_tick": 80283600,
 "belts": {"<identity>": {"rank": 1, "belt": "yellow", "points": 0}},
 "rounds": [
  {"round_id": 42, "state": "lobby", "belt": "orange",
   "lobby_tick": 80283500, "lobby_window": 240, "min_players": 3, "entrants": 2,
   "publish_tick": null, "commit_window": 300, "reveal_window": 120,
   "entry_fee": 1000, "house_seed": 5000, "match_bps": 10000, "carry_in": 0,
   "payout_mode": "podium", "bond_bps": 5000, "bond_rounds": 3,
   "rake_house_bps": 6000, "rake_dev_bps": 1000, "rake_share_bps": 3000,
   "riddle": null, "riddle_hash": null, "answer_commitment": null}
 ]}
```

While `state` is `lobby` the riddle is sealed and `riddle`, `riddle_hash`
and `answer_commitment` are null. Once published they are filled in and the
state moves to `commit`. A bot verifies `riddle_hash` against the embedded
riddle before solving, and may verify the PUBLISH transaction on chain.

Field meanings, every other endpoint, and the solver and strategy contracts
are in [docs/api.md](api.md).
