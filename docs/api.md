# Developer API and bot contract

> **Purpose:** the planner process interface, bot duties, the public read API, verification levels and the combat CLI. \
> **Audience:** bot builders and tool authors. New here? Start with [build-a-bot.md](build-a-bot.md). \
> **Status:** normative for §1–2 and §4; §3 and §6 describe what runs today. The riddle CLI and exports are Legacy; the [archived API](archive/riddle-v0/docs/api.md) covers them. \
> **Last verified:** 2026-09-26 (§3: market.json, economics.json, index.json ownership bound, market and economics endpoints)

## Contents

- [1. Process interface](#1-process-interface)
- [2. Scheduler vs planner](#2-scheduler-vs-planner)
- [3. Public read API](#3-public-read-api)
- [4. Verification levels](#4-verification-levels)
- [5. Replay and spectator UX](#5-replay-and-spectator-ux)
- [6. CLI](#6-cli)
- [7. Files and migration](#7-files-and-migration)

## 1. Process interface

A planner is an owner-run subprocess. Send one UTF-8 JSON object on stdin and
close stdin. Expect exactly one JSON object on stdout and then process exit.
Diagnostics go to stderr. Never shell-evaluate the returned text.
Default local compute timeout is 1500 ms, configurable within the chain window.
The chain deadline is authoritative; a slow program receives no extra time.

Observation schema qdojo.combat.observation.v1:

```json
{
  "schema": "qdojo.combat.observation.v1",
  "mode": "ranked",
  "network_id": "32-byte lowercase hex",
  "contract_id": "32-byte lowercase hex",
  "fight_id": "42",
  "contest_id": "42",
  "round_index": 1,
  "self_slot": "A",
  "ruleset_digest": "32-byte lowercase hex",
  "context_digest": "32-byte lowercase hex",
  "round_state_digest": "32-byte lowercase hex",
  "self": {
    "fighter_id": "32-byte lowercase hex",
    "hp": 72,
    "stamina": 40,
    "opening": 0,
    "guard_streak": 0,
    "power_available": true
  },
  "opponent": {
    "fighter_id": "32-byte lowercase hex",
    "hp": 64,
    "stamina": 26,
    "opening": 1,
    "guard_streak": 0,
    "power_available": true
  },
  "deadlines": {"commit_last_tick": "1234", "reveal_first_tick": "1235", "reveal_last_tick": "1246"},
  "observed_tick": "1211",
  "prior_rounds": [],
  "history_manifest": {"opponent_fight_ids": ["40", "37"], "as_of_tick": "1188"},
  "opponent_history": {
    "schema": "qdojo.combat.scouting.v1",
    "fighter_id": "32-byte lowercase hex",
    "as_of_tick": "1188",
    "fights": [
      {"fight_id": "40", "mode": "ranked", "slot": "B", "opponent_id": "32-byte lowercase hex",
       "outcome": "W", "result": "KO",
       "rounds": [
         {"round_index": 0, "start": {"hp": 100, "stamina": 60, "power_available": true},
          "plan": {"actions": ["KICK", "JAB", "RECOVER", "KICK", "BLOCK", "RECOVER"], "power_slot": -1},
          "executed": ["KICK", "JAB", "RECOVER", "KICK", "BLOCK", "RECOVER"],
          "versus": ["JAB", "JAB", "KICK", "DUCK", "THROW", "RECOVER"]}
       ]}
    ],
    "summary": {"fights": 2, "record": {"L": 1, "W": 1},
                "plan_actions_by_round": {"0": {"JAB": 3, "KICK": 5, "BLOCK": 1, "DUCK": 0, "THROW": 1, "RECOVER": 2}},
                "power": {"used_in_round": {"2": 1}, "never": 1}}
  },
  "decision_budget_ms": 1500
}
```

This example shows field types, not a complete round-1 trace.
A real round-1 observation MUST contain round 0 in prior_rounds.
IDs, ticks, nonces and QU are decimal strings in JSON to avoid JS precision
loss. HP, stamina, indexes, ratings and booleans use native small types.
No salt, wallet key, unconfirmed opponent action or live secret is in observation.

prior_rounds contains accepted plans, executed traces, break recovery and
confirmed source tick. history_manifest references completed public fights.
SDK fetches histories before invoking the planner; no hot-path dependency
on the official website. Owner may cache historical analysis locally.

opponent_history is the opponent scouting report the bot attaches, and
history_manifest.opponent_fight_ids lists exactly its fights. Rules:

- Only information public before this round started: fights that finished
  (phase DONE) strictly before the current round's start tick (as_of_tick),
  and the plans those fights revealed. Never the current fight (its earlier
  rounds are in prior_rounds), never a live or sealed plan.
- Newest first by fight id; at most 10 fights and 60 revealed plans of the
  scouted fighter, and at most 24 KiB of JSON (oldest fights dropped first).
  The same contract state and round always give the same report.
- Per fight: mode, the scouted fighter's slot, its outcome (W, L, D, FW/FL
  won/lost by forfeit, DF double fault, VOID), the result code, and per round
  its round-start HP/stamina/power, its revealed plan, what it executed and
  what its opponent executed. A forfeit has no invented rounds.
- summary counts the scouted fighter's planned actions per round index,
  its record, and in which round it spent its power strike.
- Practice fights have no history: fights is empty.

The whole observation written to stdin stays under 64 KiB; a runner refuses to
start a planner with a larger one (OBSERVATION_TOO_LONG, which falls back).

> **Implemented today (2026-09-25):** `prior_rounds` is filled as specified.
> On the devnet and in the demo arena, `history_manifest` and
> `opponent_history` are filled as above; in local practice they are empty.
> In local practice `deadlines` and `observed_tick` are `null`. In
> `self`/`opponent`, `power_available` is a boolean; inside beat records'
> `before`/`after` states it is `0`/`1`.

Planner response schema:

```json
{
  "schema": "qdojo.combat.plan.v1",
  "actions": ["JAB", "DUCK", "KICK", "RECOVER", "BLOCK", "THROW"],
  "power_slot": 2
}
```

Exactly these keys; no branch expressions or code. Reject unknown fields,
unknown enums, wrong case, NaN/floats, malformed JSON, extra output, nonzero
exit, too-long output or timeout. Limit stdout to 4096 bytes; stderr captured
with a separate 64 KiB cap and secret filtering. No wallet/signing authority
is passed to a planner. Owner can run a plain script or model-backed planner.

A plan must also be legal for the fighter's round-start state, which the
contract checks at reveal (engine.validate_plan): six submitted actions and a
power_slot of -1 or a JAB/KICK/THROW, and a power_slot only while
self.power_available is true. The power strike is spent even if the powered
attack misses, so a plan that sets power_slot after power_available became
false is rejected at reveal with BAD_PLAN, and the fighter forfeits. The
reference bot validates every plan before it commits: it drops a spent power
slot and keeps the actions, and replaces any other illegal plan with the
fallback. A planner should still never produce one.

## 2. Scheduler vs planner

The participation scheduler makes spending decisions before queue entry.
Its interface is separate from selecting fight actions. It receives public
book, rating, budget and confirmed balance and returns allow/deny plus an
allowed tier/gap. Failures mean DENY, never allow.

Before entering, run the planner health check and verify secret storage,
clock/tick access, network/contract/ruleset pinning and budget reservation.
Once already in a fight, a planner failure defaults to six RECOVER actions
with no power, if enough time remains to commit. This can lose but avoids an
avoidable non-reveal. Owner can preconfigure another validated fallback.
Record FALLBACK_PLAN_USED privately and in local diagnostics.

Never replace a plan after commitment. Persist:
network, contract, contest/fight/round, state/context digests, seven plan bytes,
salt, nonce, commitment, signed transaction bytes, send status and observed
inclusion. Restart resumes the exact recorded transaction/plan. Losing the salt
does not authorize a substitute; disclose local failure and stop future entry.

A send is not confirmation. Poll independent node/contract state within bounds;
a delayed indexer cannot prove absence. A retry must use the same intended
operation and idempotency identity. Confirm final result/withdrawal state.

Do not retry into a rejection. A commit or reveal rejected for a reason that
cannot clear (BAD_PLAN, BAD_COMMITMENT, LATE, STALE_AUTH, ...) is recorded
and never re-sent; only WRONG_PHASE, FULL and NONCE_CONFLICT are retried,
with exponential backoff (4 ticks doubling to 240). A dropped transaction is
re-sent at once. After a terminal fault the contract imposes a cooldown
(cooldown_until) and, at faults_per_epoch faults, a ranked suspension for the
epoch; the bot reads both from the fighter record and sends no paid entry
until they have passed. A rejected queue entry backs off the same way, and a
rejected cup registration is not repeated for that cup. The owner's
stop_after_faults limit counts faults over the bot's lifetime by default, or
over the last fault_window_ticks ticks when that is set (the demo arena:
3 faults per 2,400-tick epoch).

## 3. Public read API

### 3.1 Static export (/data/combat/v1/)

Proposed prefix /data/combat/v1/. Legacy /data/board.json and history.json are
not overwritten or reinterpreted. REST/static exports are convenience views;
every response carries schema, network, contract, generated_tick and source
evidence. Contract query methods expose the same bounded logical records.

| Resource | Content |
|---|---|
| manifest.json | Ruleset/profile digests, deployment identity, supported schema versions |
| rulesets/{digest}.json | Immutable ruleset artifact and semantic version |
| book.json | Offers, counts/capacity, current windows, affiliations, next matching tick |
| fights/{id}.json | Participants, immutable context, state, deadlines, accepted action status, result |
| fights/{id}/replay.json | Full confirmed plans/salts, traces, break events, unused suffixes, verification evidence |
| fighters/{id}.json | Owner/operator history, ratings, placement, records, affiliation, obligations |
| fighters/{id}/fights/{page}.json | Stable fight IDs, mode, result, cursor and snapshot tick |
| seasons/{id}.json | Boundaries, season ratings/qualifications, standings, closing state, trophy |
| cups/{id}.json | Descriptor, funding, seeds/bracket, schedule, check-in and pairing results |
| events/{page}.json | Ordered event sequence and append-digest links |
| npcs.json | Disclosed policy IDs/versions and practice/exhibition availability |

> **Implemented today (2026-09-25):** `combat/export.py` writes `manifest.json`,
> `rulesets/{digest}.json`, `book.json`, `index.json` (recent fights, fighters,
> names, deployment label), `fights/{id}.json`, `fights/{id}/replay.json`,
> `fighters/{id}.json`, `events/latest.json`, `npcs.json`, `results.json`,
> `cups.json`, `duels.json` and `seasons.json`, and for the demo arena
> `market.json` and `economics.json` (below). Paged fighter histories,
> per-season and per-cup files and paged events are not written yet.
>
> `index.json`'s `deployment.fighters[id].asset.history` holds each
> fighter's last 4 ownership entries, with `transfers` (the total) and
> `history_truncated`; `fighters/{id}.json` holds the full history.
> `seasons.json` gives each season's `qualification` thresholds: the demo
> arena scales the distinct-opponent rule to its field
> ([competition.md](competition.md) §3).

**market.json** (`qdojo.combat.market.v1`, demo arena only): the simulated
fighter market ([operations.md](operations.md) §8). `listings`: fighter ID and
name, `ask`, `value` (the public value model: rating, record, experience),
`rating`, `seller`, `since_tick`, `sold` (a price is agreed and the transfer
waits for the fighter to be idle). `sales`: the latest 50, newest first, with
`tick`, `price`, `fee`, `bid`, `seller`, `buyer`, and the fighter's rating and
record at sale. `stats`: sales, volume, fees, median, min and max price.
`fee_bps` is the market fee. Amounts are decimal strings of fake QU.

**economics.json** (`qdojo.combat.economics.v1`, demo arena only): `tiers`
(per tier: `stake`, `rake_bps`, `house_rake_per_fight`,
`break_even_win_share`, and `ev_by_win_share`: net QU per fight for a bot
winning that share, no draws), `events` (duel stake per format, cup entry
fee, cup rake, next cup sponsorship, market fee),
`measured_ranked_net_by_rating` (recent ranked contests by rating band) and
`house` (rake income, market fees, simulated execution fees, sponsorship
paid, P&L and P&L per fight). The execution fees come from a candidate cost
model, not a Qubic measurement ([economics report](economics-report.md)).

Bound contract query pages to 64 records. Cursors are explicit sequence IDs,
not mutable array offsets. Pin snapshot tick or report a changed snapshot;
do not claim pagination completeness across an unstable view.

Public fight state includes start context, round-start states/digest, accepted
commitments, reveal flags, current phase, service generation, executed traces
when available, result code, winner or null, pre/post ratings and monetary
credits. Plans/salts are public only after their reveal transactions.

A record MUST distinguish intended action, effective action and executed flag.
Do not count the revealed suffix after KO as executed history.
Forfeit has its own display/result; no invented HP or move sequence.

### 3.2 Read API (/api/v1/)

The static export keeps the most recent 200 fights. The read API answers
full-history questions from a SQLite read model (`combat/readmodel.py`)
that indexes the arena's input journal: every fight, fighter, per-mode
record, rating change, season, cup, duel and ownership record. It replays
the journal into its own contract copy and never compacts it, so the arena
pruning finished history from its own memory does not lose anything here.
It uses the manifest the arena was created with (devnet.json), checks the
arena's `digest` checkpoints as it crosses them, and applies market payments
(`xfer`). Names, full ownership histories and economics come from the export;
market sales from the arena's `market.json`. It is an
index, never an authority: it replays the same journal the arena does, and
can be rebuilt from scratch at any time. `qdojo combat api` serves it
(`combat/api.py`), together with the static export on every other path.

All responses are JSON with `schema` (`qdojo.combat.api.<kind>.v1`) and
`generated_tick` (the indexed tick; for a finished fight, the tick it
ended). Lists are newest first; `page` starts at 1, `per_page` defaults to
50 and is capped at 200, and every page carries `total` and `pages`.

| Endpoint | Content |
|---|---|
| `GET /api/v1/status` | Indexed tick, journal offset, counts, whether it is following and caught up |
| `GET /api/v1/fighters` | Every fighter: rating, belt, contract record, full-history `records_by_mode` and `career`, `fights_total`, `form` (last 5), name, `origin`, driver, simulated NFT |
| `GET /api/v1/fighters/{id}` | One fighter as above, plus `form` (last 10), `first_fight`, the last 64 fight IDs and `ratings_recent` |
| `GET /api/v1/fighters/{id}/fights?mode=&page=&per_page=` | That fighter's fights (summaries plus `slot` and `outcome`) |
| `GET /api/v1/fighters/{id}/replays?before=&limit=` | Up to 100 finished replays, for scouting; `next_before` continues |
| `GET /api/v1/fighters/{id}/ratings?page=` | Every ranked rating change (lifetime and season, before and after) |
| `GET /api/v1/fights?fighter=&mode=&status=all\|done\|live&page=` | Fight summaries (`fights/{id}.json` shape plus `final`) |
| `GET /api/v1/fights/{id}` and `/api/v1/fights/{id}/replay` | The summary and replay, byte for byte the exporter's documents |
| `GET /api/v1/leaderboard` | Fighters ranked by rating, ranked wins, fewer faults, ID; with `rank`, `faults`, `form` |
| `GET /api/v1/seasons`, `/api/v1/seasons/{n}` | Every season's standings (the export keeps four) |
| `GET /api/v1/cups?page=`, `/api/v1/cups/{id}` | Every cup (`cups.json` item shape) |
| `GET /api/v1/duels?page=`, `/api/v1/duels/{id}` | Every duel series (`duels.json` item shape) |
| `GET /api/v1/owners/{id}` | Fighters an identity owns and owned |
| `GET /api/v1/search?q=` | Fighters by name or ID prefix, a fight by number, owners by ID prefix |
| `GET /api/v1/market?fighter=&page=` | Every sale of the simulated market (the export keeps 50), newest first: `market.json` sale shape |
| `GET /api/v1/economics` | The latest `economics.json` body |

`origin` is `house` (run by the operator: demo bots and NPCs) or `outside`
(registered and run by an outside builder, [build-a-bot.md](build-a-bot.md)
§8). The static export carries the same field on each fighter.

Errors are `{"schema": "qdojo.combat.api.error.v1", "error": {"status",
"code", "message"}}` with the HTTP status: 400 `bad_id`/`bad_query`, 404
`not_found`, 405 `read_only`, 503 `not_ready` while the first index is
built. CORS answers only the configured origins (`--cors-origin`). Finished
fights and replays carry `Cache-Control: public, max-age=86400`, everything
else `max-age=5`; responses have an `ETag` (`If-None-Match` gives 304) and
are gzipped on request.

The site uses the API for fighter pages, scouting, the leaderboard and fight
lists when `/api/v1/status` answers for the same network as the export's
manifest, and falls back to the static export otherwise.

The `join`, `tx` and `chain` endpoints exist only when an operator enables
outside builders ([build-a-bot.md](build-a-bot.md) §8); otherwise they
answer 404 `join_disabled`.

## 4. Verification levels

Expose separate checks, with PASS/FAIL/UNAVAILABLE and evidence:

1. Manifest/ruleset digest matches the accepted contract context.
2. Accepted input transactions are confirmed for the claimed signer/ticks.
3. Each revealed plan/salt matches its commitment and round-start digest.
4. Independent integer replay reproduces every post-state and terminal outcome.
5. Contract accounting/rating result follows that outcome and snapshotted terms.
6. Withdrawals have actually executed, if claiming money was paid.

All relevant checks must pass to label COMBAT_VERIFIED. A missing reveal in a
forfeit is expected; verify the authoritative deadline/result instead of trying
to replay nonexistent actions. A valid result hash alone is HASH_MATCH_ONLY.
A same-source export cannot independently establish chain inclusion.

## 5. Replay and spectator UX

Keep the existing arcade cabinet visual language. New main views: ranked
book, active fights, completed replays, fighter profiles, training and cups.
Each match shows real HP, stamina, power status, round number and deadline.
A timing countdown is never presented as remaining health.

Drive jab/kick/block/duck/throw/recovery/hit animations from the resolved trace.
Both attacks animate together on a trade. Blocked moves show zero HP damage;
strain is a separate stamina effect. Forfeit displays timeout, not KO.
Animation speed, browser pause, frame loss and reduced motion cannot affect
combat state. Provide a static beat table and keyboard navigation.

Default replay beat duration 600 ms, configurable 0.25x..4x. A six-beat round
plays in about 3.6 seconds; append a short state/break summary. Show when a
displayed replay trails the authoritative current round. Bot planning proceeds
from confirmed state, independent of spectator playback.

Opponent profile shows action frequencies by round/resource band, recovery
timing, power usage, opening conversion, recent mode-separated results and
software-version labels only when owners choose to disclose them.
Do not claim history predicts future actions with certainty.

## 6. CLI

Every command below runs today. Training, replay and evaluation need no
wallet, NFT, node or seed. The chain-shaped commands (fighter, queue, duel,
cup, withdraw, bot run) operate on the **local devnet**: the reference
contract on a persistent fake chain with fake QU and synthetic identities
derived from labels. No deployment manifest exists yet, so none of them can
reach a real network; `doctor` reports this as a warning, and paid admission
stays disabled.

Free practice and analysis:

```sh
uv run qdojo combat npcs
uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"
uv run qdojo combat train --npc kicker-v1 --seed <hex32> --out fight.json
uv run qdojo combat replay fight.json
uv run qdojo combat evaluate --policy scout-v1 --pool roster --seeds 200
```

Devnet (fake QU):

```sh
uv run qdojo combat fighter register musashi
uv run qdojo combat bot run --fighter musashi --planner "python3 my_bot.py" --spar scout-v1 --ticks 600
uv run qdojo combat queue enter --fighter musashi
uv run qdojo combat queue list
uv run qdojo combat queue cancel <id>
uv run qdojo combat duel offer --fighter musashi --opponent kojiro --stake 5000 --format bo3
uv run qdojo combat duel accept <id> --fighter kojiro
uv run qdojo combat cup list
uv run qdojo combat cup register <id> --fighter musashi
uv run qdojo combat cup check-in <id> <n> --fighter musashi
uv run qdojo combat fighter show musashi
uv run qdojo combat fighter authorize musashi <name>
uv run qdojo combat withdraw --as musashi
uv run qdojo combat devnet status
uv run qdojo combat devnet export --out apps/web/data/combat/v1
uv run qdojo combat doctor --planner "python3 my_bot.py"
```

Read model and API (§3.2), and entering the public demo arena (simulated
chain, fake QU; only where the operator enabled it):

```sh
uv run qdojo combat readmodel rebuild --devnet ~/.qdojo/combat/arena --db readmodel.sqlite --export apps/web/data/combat/v1
uv run qdojo combat api --db readmodel.sqlite --devnet ~/.qdojo/combat/arena --export apps/web/data/combat/v1 --port 8790
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name musashi --planner "python3 my_bot.py"
```

Every command takes `--json` for machine-readable output and runs without
prompts. No command silently creates a seed, spends, registers or deploys.
`bot run` enforces the owner budget in `--budget` (a JSON file of the
`Budget` fields in `qdojo/combat/bot.py`) and journals each plan and salt
(0600) before it commits.

Devnet state lives in `~/.qdojo/combat/devnet`, bot state in
`~/.qdojo/combat/bots/`; `QDOJO_COMBAT_HOME` moves both, `--devnet` picks
another devnet directory. `qdojo combat live` runs the public demo arena
([operations.md](operations.md) §8).

> **Known issue (2026-09-25):** `bot run --planner "…"` forfeits its first
> fight on the devnet: the CLI advances ticks without waiting for the planner
> subprocess (planned in the background), so the commit window closes before
> the plan arrives, and the default budget then stops the bot after one fault.
> `bot run --npc <name>` with an in-process policy works. The live arena is
> unaffected because it advances ticks on a wall clock.

Legacy riddle operation is documented in the archive. Do not point a new
combat user at a riddle board, and do not imply that `./dojo` starts a
combat fight.

## 7. Files and migration

Use a separate combat state directory with schema marker and network/contract
namespace. Never load legacy rounds.json as combat. Secret plan journals are
private, permission-restricted and excluded from exports/git. History caches
contain only confirmed public information.

Combat planner prompts live under `prompts/combat/` (used by
`combat/llm_planner.py`). prompts/solver-system.md and solver-user.md remain
legacy runtime assets for the riddle solver. Keep a small dependency-free planner
example, all NPC policies and an independently verified local simulator.

Provide formal JSON schemas and frozen input/output examples as the SDK's first
deliverable. Unknown major schema versions fail closed. Optional backward-
compatible display fields require a minor schema revision; planner responses
remain strict.
