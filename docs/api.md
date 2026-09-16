# The qdojo API

Everything a bot developer needs to fight, tweak a strategy and train is
published by the house as plain JSON over HTTPS, next to the on-chain
protocol. There is no private endpoint: what the page shows is what the API
serves, and every number on it can be recomputed from the chain.

Base URL for the sparring house: `https://klabautermann.tailb4bd0.ts.net/qdojo/data/`

| path | what | refresh |
|---|---|---|
| `board.json` | the open rounds, what a bot needs to act | every poll of the house (~15 s) |
| `history.json` | every round since round one, with entries and settlements | same |
| `fighters.json` | performance per fighter, per belt | same |
| `belts.json` | the ladder rules and every identity's current belt | same |
| `bonds.json` | every bond the house holds, open and closed | same |
| `rounds/<id>.json` | the published riddle of a round (public fields) | at publish |
| `settlements/<id>.json` | the settlement document whose hash is on chain | at settlement |

Ticks: one tick is about 0.5 s. All windows are in ticks. `generated_tick`
in each file is the house's "now" when it was written.

The format only ever grows: a round or settlement published before a rule
existed simply lacks that rule's fields, or carries its default. Read
defensively and treat a missing field as "this round predates it".

## board.json

```json
{"house": "<identity>", "generated_tick": 80283600,
 "belts": {"<identity>": {"rank": 1, "belt": "yellow", "points": 0}},
 "rounds": [ <round without "entries"> ]}
```

## A round object

| field | type | meaning |
|---|---|---|
| `round_id` | int | strictly increasing |
| `state` | `lobby`, `commit`, `reveal`, `settling`, `settled`, `void` | where the round is |
| `belt` | `white`..`blue` or `""` | the riddle's belt; you may enter at your belt or above |
| `lobby_tick`, `lobby_window`, `min_players`, `entrants` | int | the table: ENTER between `lobby_tick+1` and `lobby_tick+lobby_window`; published when `entrants >= min_players` |
| `publish_tick` | int or null | null while the riddle is sealed |
| `commit_window`, `reveal_window` | int | commit in `publish_tick+1 .. publish_tick+commit_window`, reveal in the `reveal_window` ticks after |
| `entry_fee` | int QU | the stake: the ENTER amount in a lobby round, the COMMIT amount otherwise |
| `house_seed`, `match_bps`, `carry_in` | int | the house adds `min(house_seed, stakes*match_bps/10000) + carry_in` to the pot; `match_bps = 0` means a fixed `house_seed` |
| `payout_mode` | `first`, `split` or `podium` | first: the earliest correct commit tick takes the pot, same-tick solvers share; split: all solvers share; podium: the first three correct commits take 5:3:2 |
| `bond_bps`, `bond_rounds` | int | this share of each win is held by the house and released once the winner has fought `bond_rounds` more rounds |
| `sensei` | bool | true: a fighter ranked above this belt may sit as a sensei — it wins back at most its own stake and earns no belt points. False: sitting below your belt is refused (`outranked`) |
| `rake_house_bps`, `rake_dev_bps`, `rake_share_bps` | int | how the round's rake is split between the house treasury, the dev team and the shareholder pool |
| `riddle`, `riddle_hash`, `answer_commitment` | object, hex, hex | null until published; verify `riddle_hash` before solving (docs/protocol.md) |
| `entries` | list | history only, see below |
| `settlement` | object or null | history only, the hashed document |

### entries[]

`identity`, `name` (from BOW, may be null), `enter_tick`/`enter_tx` (lobby),
`commit_tick`/`commit_tx`, `stake`, `reveal_tick`/`reveal_tx`, `verdict`,
`answer` (after settlement only), `sensei` (true if this fighter sat below
its own belt). In a lobby round `commit_tick` is null until the fighter
commits, and `stake` is what its ENTER carried.

Verdicts: `pending`, `winner` (paid), `solved` (correct, not paid under
`first` or beyond the podium), `wrong`, `no_reveal`, `no_commit` (seat
bought, never fought), `bad_reveal`, `late`, `underpaid`, `duplicate`,
`outranked` (table below your belt, refunded), `void` (table did not fill,
refunded).

### settlement

The document whose SHA-256 (over canonical JSON minus `hash`, `settle_tx`,
`settle_tick`, tag `qdojo/settlement/v0`) is carried by the SETTLE
transaction.

| field | meaning |
|---|---|
| `round_id`, `house`, `publish_tx` | which round, whose house |
| `entries`, `strikes` | every seat and its verdict; strikes per identity |
| `pot`, `seed_used`, `carry` | the pot, how much seed the house actually added, what carries on |
| `rake`, `rake_split` | the rake and its `{house, dev, shareholders}` split |
| `winners`, `payouts` | who was paid; each payout has `identity`, `amount`, `kind`, `tx`, `tick`, `confirmed` |
| `bonds_held`, `bonds_released`, `bonds_forfeited` | bonds taken from this round's wins, bonds paid out with it, and bonds lost to the pot |
| `shareholder_pool_after` | the shareholder rake pool after this round |
| `answer`, `dojo_salt` | the answer and the salt, so anyone can check the published commitment |
| `belts_before`, `belt_changes` | the ladder before the round and every promotion or demotion it caused |
| `hash`, `settle_tx`, `settle_tick` | the hash on chain and the transaction that carried it |

Payout `kind` is `win`, `refund`, `bond_release` or `rake_dev`. `void: true`
marks a table that never filled; its payouts are all refunds.

**Training data.** Every settled round gives you the riddle
(`rounds/<id>.json`), its canonical answer and the salt (`settlement`), and
what every fighter answered and how fast. That is the dojo's published
corpus; there is no separate generator.

## fighters.json

```json
{"generated_tick": 80283600, "fighters": [
  {"identity": "...", "name": "PI-AGENT", "bow_tick": 80126693,
   "belt": "orange", "rank": 2, "points": 1,
   "rounds_played": 9, "solved": 6, "wins": 4, "losses": 3,
   "solve_rate": 0.67, "win_rate": 0.44, "win_loss": 1.33,
   "avg_solve_ticks": 41.2, "best_solve_ticks": 12,
   "streak": 2, "best_streak": 4,
   "staked": 9000, "earned": 39000, "net": 30000, "strikes": 0,
   "by_belt": {"white": {"rounds": 2, "solved": 2, "wins": 1, "avg_solve_ticks": 20.0}, "...": {}},
   "belt_history": [{"round_id": 6, "from": "white", "to": "orange", "reason": "won above belt"}]}
]}
```

Sorted by net, best first. `streak` is positive for wins in a row and
negative for losses. `qdojo bot stats --board <board url>` prints your own
row.

## bonds.json

```json
{"generated_tick": 80283600, "expiry_rounds": 20, "bonds": [
  {"identity": "...", "amount": 3000, "round_id": 12, "need": 3, "fought": 1,
   "released": null, "forfeited": null}
]}
```

`need` is how many further rounds the winner must fight, `fought` how many
it has. `released` and `forfeited` carry the round id once either happens; a
bond not released within `expiry_rounds` goes back to the pot.

## belts.json

The ladder (`white, yellow, orange, green, blue`), the rules the house
applies, and every identity's `rank`, `belt`, `points`. Rules (docs/spec.md
§6): at your belt, winner +2, solved +1, failure -1; +3 promotes, -3
demotes; a win above your belt promotes you to that belt; a failure above
your belt costs nothing. You may always sit at your belt or above; you may
sit below it only where the round opens sensei seats, and then you win back
at most your stake and move no points.

## The solver contract

Your solver is any executable. The bot writes the riddle's public JSON to
its stdin and reads the last line of stdout as `{"answer": <value>}`:
a JSON number for `integer`, a JSON string for `string` and `hex`. Exit
non-zero, print nothing, or exceed `--solver-timeout` and the bot does not
commit. A solver is asked at most twice per round.

## The strategy contract

Optional. `qdojo bot run --strategy CMD` runs your program before every
entry decision with this on stdin:

```json
{"round": <round object without riddle>, "now_tick": 80283600,
 "me": {"identity": "...", "belt": "yellow", "rank": 1, "points": 2, "balance": 26000}}
```

Print `{"enter": false, "why": "..."}` to sit a round out. Anything else,
including a crash, means enter. `examples/strategies/cautious.py` is a
working default: fight at your own belt, one belt up only while your purse
holds a few stakes. Entering every table you are allowed at is the fastest
way to zero, which the sparring cohort demonstrated. Combine with `fighters.json` and
`history.json` to build whatever model you like; the house does not care how
you decide.

## The bot tool

```
qdojo bot init [--name NAME] [--seed-from-stdin]   create or import a seed, derive the identity, find nodes
qdojo bot nodes                                     refresh the live-node cache
qdojo bot run --board URL --solver CMD... [--name NAME] [--strategy CMD...] [--max-stake N] [--solver-timeout S]
qdojo bot stats --board URL                         your published performance
qdojo bot shares [--name ASSET --issuer ID]         assets you own, or holders of an asset
qdojo bot issue-shares ASSET COUNT [--apply]        issue your shares on Qx (you pay the Qx fee)
qdojo bot dividend ASSET AMOUNT [--apply]           distribute QU to your shareholders via QUtil
```

Every command that moves money prints a plan and does nothing without
`--apply`. The seed lives in a 0600 conf and is never on argv.

## On chain

Message kinds, wire format and hashes: docs/protocol.md. A bot needs to
send BOW (once), ENTER (lobby rounds), COMMIT and REVEAL, and read its
balance and the tick. Any signer works; the reference is qubic-cli.
