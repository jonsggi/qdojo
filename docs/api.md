# Developer API and bot contract

> **Purpose:** the planner process interface, bot duties, the public read API, verification levels and the combat CLI. \
> **Audience:** bot builders and tool authors. New here? Start with [build-a-bot.md](build-a-bot.md). \
> **Status:** normative for §1–2 and §4; §3 and §6 describe what runs today. The riddle CLI and exports are Legacy; the [archived API](archive/riddle-v0/docs/api.md) covers them. \
> **Last verified:** 2026-09-25

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
> `cups.json`, `duels.json` and `seasons.json`. Paged fighter histories,
> per-season and per-cup files and paged events are not written yet.

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
