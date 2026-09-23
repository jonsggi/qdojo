# Combat developer API and bot contract

Status: target combat-v1 API. Existing riddle CLI and exports remain legacy.
No combat command in this document is claimed to run yet.
Start with [spec.md](spec.md), [combat.md](combat.md), [protocol.md](protocol.md).
The [archived API](archive/riddle-v0/docs/api.md) describes current riddle code.

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
  "history_manifest": {"opponent_fight_ids": [], "as_of_tick": "1210"},
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

## 6. Planned CLI delivery

These command names are implementation requirements, not currently runnable:

| Planned command | Purpose |
|---|---|
| qdojo combat train | Free local fight against an NPC; optional deterministic seed |
| qdojo combat evaluate | Batched side-swapped benchmark; separate train/test seeds |
| qdojo combat replay | Verify/replay a recorded fight |
| qdojo combat bot run | Owner-limited autonomous queue/commit/reveal loop |
| qdojo combat queue enter / cancel / list | Inspect and manage a funded offer |
| qdojo combat duel offer / accept / cancel | Named series |
| qdojo combat cup list / register / check-in | Scheduled competition |
| qdojo combat fighter show / authorize | Ownership, record and operator controls |
| qdojo combat withdraw | Confirmed withdrawal of credits to self |
| qdojo combat doctor | Non-spending readiness and configuration check |

All should support machine-readable output and noninteractive operation.
No command silently creates a seed, spends, registers or deploys in training.
Windows and Linux bot support must retain current portability boundaries.

For the existing code, the following is a read-only parser check:

```sh
uv run qdojo bot --help
```

Actual legacy operation is documented in the archive; do not point a new combat
user at a riddle board or imply current ./dojo starts a combat fight.

## 7. Files and migration

Use a separate combat state directory with schema marker and network/contract
namespace. Never load legacy rounds.json as combat. Secret plan journals are
private, permission-restricted and excluded from exports/git. History caches
contain only confirmed public information.

Add combat-specific planner prompts under a new namespace during implementation.
Existing prompts/solver-system.md and solver-user.md remain legacy runtime
assets until their callers migrate. Keep a small dependency-free planner
example, all NPC policies and an independently verified local simulator.

Provide formal JSON schemas and frozen input/output examples as the SDK's first
deliverable. Unknown major schema versions fail closed. Optional backward-
compatible display fields require a minor schema revision; planner responses
remain strict.
