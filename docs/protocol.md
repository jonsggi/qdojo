# Combat protocol v1

Status: target specification, NOT the implemented riddle v0 wire format.
[spec.md](spec.md) owns money/identity; [combat.md](combat.md) owns mechanics.
Legacy 0x444F/DOJO messages continue to mean riddle v0 only.

## 1. Platform and transport

Target is a Qubic contract with bounded integer state and work. Contract
procedures/state, tick callbacks, transfer behavior and execution-reserve
costs are described in the primary [Core documentation](https://github.com/qubic/core/blob/main/doc/contracts.md)
and [execution-fee documentation](https://github.com/qubic/core/blob/main/doc/execution_fees.md),
checked 2026-09-21. Pin a Core commit for implementation and test its actual
ABI, ownership and transfer behavior. Do not infer them from another chain.

Deployment manifest identifies network, contract identity/index, public
procedure IDs, ruleset and timing profile. The private-key signing algorithm
remains the existing verified Qubic signer; the game commitment below is a
separate SHA-256 operation.

Use one contract user procedure Dispatch with fixed `Array<uint8,512>` input,
and read-only query functions with bounded pages. Dispatch's numeric procedure
ID is a deployment value, not legacy inputType 0x444F.

Canonical request, all multibyte integers unsigned little-endian:

| Offset | Length | Field |
|---|---:|---|
| 0 | 4 | ASCII QDC1 |
| 4 | 2 | opcode |
| 6 | 2 | flags, zero in v1 |
| 8 | 8 | request_nonce |
| 16 | 2 | body length, 0..487 |
| 18 | 6 | reserved zero |
| 24 | body length | opcode-specific body |
| following body | to byte 510 inclusive | zero padding |
| 511 | 1 | required framing sentinel 0xA5 |

Byte count is exactly 512 in the native SDK. Unknown opcode, nonzero reserved
bits/padding or absent sentinel rejects without mutation except refund credit.
The sentinel detects zero-padded short inputs. Qubic may truncate oversized
inputs before invoking a function: contract code must not claim it can detect
bytes the runtime discarded. Test actual truncation; SDK refuses noncanonical
lengths, and the interpreted 512-byte request is the semantic request.

Every admitted monetary operation validates attached amount before consuming it.
Rejected attachments return to invocator as withdrawal credit; do not silently
retain excess as a donation. Funding and refund accounting must count incoming
transfer once even if a platform callback also reports it.

Direct authenticated transactions only for fighter actions in v1: invocator
must equal originator and the bound owner/operator as appropriate. An arbitrary
calling contract is not implicitly a delegated fighter operator.

## 2. Hashes and fixed encodings

Game hashes are SHA-256, 32-byte raw output; domain strings below include the
terminal zero byte. No identity ASCII, hex text, JSON whitespace or host struct
padding enters a combat commitment.

SHA-256 is an explicit game choice. If the pinned QPI lacks a suitable public
primitive, implement/review a bounded SHA-256 helper inside the restricted
contract language and benchmark it. Do not silently substitute K12 or assume
the repository's transaction K12 variant equals a game hash. This helper and
its NIST/reference vectors are a contract milestone.

Network ID is a manifest 32-byte constant, different on every development/test/
production deployment. Contract ID is the actual 32-byte contract public key.

Participant record, in order:
`fighter_id[32], owner[32], operator[32], auth_version u32,
payout_recipient[32], lifetime_rating u16, season_rating u16`.
Order participants by fighter ID.

Fight context bytes, in order:
`network_id[32], contract_id[32], contest_id u64, fight_id u64,
mode u8, series_format u8, cup_id u64, season_id u32, start_tick u64,
ruleset_digest[32], commit_ticks u16, reveal_ticks u16,
fee_profile_id u32, stake_per_fighter u64, rake_bps u16,
house_bps u16, dev_bps u16, share_bps u16,
house_recipient[32], dev_recipient[32], share_recipient[32],
participant_A, participant_B`.

Modes: 0 RANKED, 1 DUEL, 2 CUP, 3 EXHIBITION. Exhibition is zero stake,
no fees/rating and no admission to paid ranked. Practice can run locally
without any on-chain identity. Formats: 0 SINGLE, 1 BO3, 2 BO5.
Unused cup_id/season_id are zero. IDs begin at 1.

`context_digest = SHA256("qdojo/combat/context/v1\0" || context_bytes)`.

Fighter mechanical state is eight bytes:
`hp u16, stamina u16, opening u8, guard_streak u8,
power_available u8, reserved u8=0`.

`round_state_digest = SHA256("qdojo/combat/state/v1\0" ||
context_digest || round_index u8 || state_A || state_B)`.

This hashes the ROUND-START state including inter-round recovery, not the state
after the first reveal. It remains unchanged throughout that round's windows.

Plan bytes are actions as six u8 IDs in beat order, followed by power_slot u8:
0..5 or 255 for unused (-1 in JSON). Legal actions are 0..5 only.

Commitment preimage, in exact order:

```text
"qdojo/combat/commit/v1\0"
network_id[32]
contract_id[32]
fight_id u64
round_index u8
context_digest[32]
round_state_digest[32]
fighter_id[32]
operator[32]
auth_version u32
salt[32]
plan[7]
```

Commitment = SHA256(preimage). Salt is 32 independently generated cryptographically
random bytes. Never reuse a salt; never derive it from a public identity,
tick or plan. Persist salt and exact plan before sending COMMIT. No public
seed/plan logs while it is secret.

Ruleset digest is SHA256 of `"qdojo/combat/rules/v1\0"` followed by canonical
JSON of [combat-v1.json](combat-v1.json): UTF-8, keys lexicographically sorted,
no whitespace, ASCII strings, integer values only, no trailing newline.
The JSON includes semantic_version; changing mechanics as well as numbers
requires changing it. Contract embeds the digest and matching constants.
Test code and vectors against that artifact; the contract need not parse JSON.

A frozen synthetic [commitment fixture](fixtures/commitment-v1.json) supplies
context bytes, state bytes, plan bytes, full preimage and expected digests.
Its expected commitment is
`f0754c65c5aaea97811a9a64b46696084c419abd29a80853af538b017c0742fe`.
The fixture salt is public test data and MUST NOT be used for live play.

## 3. Procedures and payloads

The following opcodes and field order are normative. Every body begins with
the fields listed, without host alignment. Extra body bytes reject.

| Opcode | Operation | Body |
|---:|---|---|
| 1 | RegisterFighter | fighter_id[32], registry_version u32 |
| 2 | SetOperator | fighter_id[32], new_operator[32], expected_auth_version u32 |
| 3 | QueueEnter | fighter_id[32], auth_version u32, ruleset_digest[32], timing_profile_id u32, fee_profile_id u32, tier_id u16, max_gap u16, expires_tick u64 |
| 4 | QueueCancel | offer_id u64 |
| 5 | DuelOffer | fighter_id[32], auth_version u32, opponent_id[32], ruleset_digest[32], timing_profile_id u32, fee_profile_id u32, stake u64, format u8, expires_tick u64 |
| 6 | DuelAccept | offer_id u64, fighter_id[32], auth_version u32 |
| 7 | Commit | fight_id u64, round_index u8, fighter_id[32], auth_version u32, round_state_digest[32], commitment[32] |
| 8 | Reveal | fight_id u64, round_index u8, fighter_id[32], auth_version u32, round_state_digest[32], salt[32], plan[7] |
| 9 | Advance | target_kind u8, target_id u64 |
| 10 | Withdraw | empty |
| 11 | CupRegister | cup_id u64, fighter_id[32], auth_version u32 |
| 12 | CupWithdraw | cup_id u64, fighter_id[32] |
| 13 | CupCheckIn | cup_id u64, pairing_id u64, fighter_id[32], auth_version u32 |
| 14 | DuelCancel | offer_id u64 |

RegisterFighter binds an already recognized registry asset after confirming
ownership; it does not mint an NFT or invent an asset ID. Issuance/registry
administration and cup creation are deployment administration interfaces, with
their own reviewed manifest-controlled authorization; see §8.

QueueEnter, DuelOffer/Accept and CupRegister attach exact amounts. Other player
operations attach zero; unexpected amounts are refunded and operation rejected.
RegisterFighter attaches zero: acquisition is separate from this binding call.

SetOperator is owner-only at IDLE or an unchecked tournament pairing boundary
(as specified in spec.md), verifies expected version and increments it.
QueueCancel/DuelCancel accept either original owner or original authorized
operator, or new confirmed owner solely to cancel after transfer. Refund still
goes to original payer. Withdraw is the credited recipient only.

For nonce-bearing mutations, keep last accepted nonce, request digest and result
per admitted signer. Accept only increasing nonce; identical retry of the
most recent request returns its stored result with no repeated funding action.
Same nonce/different content rejects NONCE_CONFLICT; older nonce rejects STALE.
A second attached transfer on any duplicate is refunded, not added to old escrow.
Rejected operations do not advance nonce. Advance uses nonce=0 and is public;
it can process only mechanically eligible progress, never choose a winner.
A terminal target returns its terminal status idempotently.

Signers store next nonce durably. New, unknown invocators cannot fill arbitrary
nonce storage: only registry-backed authorized users or existing credit owners
receive state slots. Admission-capacity failure rejects and refunds.

## 4. Fight state machine and deadlines

Candidate timing profile: commit_ticks=24, reveal_ticks=12.
These are tick counts, not a claim about seconds. Benchmark the live-network
distribution before locking a production profile.

At fight creation in END_TICK T:
phase=COMMIT, round=0, start_tick=T, C=T+24, R=C+12.
Accept COMMIT only on ticks T+1 through C inclusive.
Accept REVEAL only on ticks C+1 through R inclusive.

Do not shorten the commit window after early commitments. A client reveals
only after observing both valid commitments confirmed and commit window closed.

END_TICK processing, after all same-tick user transactions:

- At C, if both committed, transition to REVEAL.
- At C, if exactly one committed, it wins whole contest by opponent forfeit.
- At C, if neither committed, terminal DOUBLE_FAULT.
- During REVEAL, if both valid reveals exist, resolve the round at END_TICK.
- At R, if exactly one valid reveal exists, it wins whole contest by forfeit.
- At R, if neither valid reveal exists, terminal DOUBLE_FAULT.
- A reveal landing at R counts before timeout classification.
- If round resolves nonterminal at T2, apply the +10 break recovery once,
  set next round's start=T2, C=T2+24, R=C+12. Commit opens at T2+1.
- If terminal, record outcome/accounting/rating once and release/rescope locks.

A completed first round can shorten the reveal portion but not the next round's
commit portion. Public round plans and start state are available immediately
from that resolved tick. Renderers can play it while the bots plan the next one.

Commit first valid per fighter wins. Exact duplicate is harmless; different
second commitment is ALREADY_COMMITTED. Invalid reveals (wrong salt/state,
bad actions, unauthorized) are rejected without replacing the commitment.
First valid reveal counts; exact duplicate is harmless. No retries extend time.

Requests before/after the phase reject WRONG_PHASE/LATE. Malformed requests
never invalidate the opponent's valid action. Terminal error classification
uses only valid accepted records, not counts of failed attempts.

## 5. Objective service failure

A contract unable to run because its execution reserve is exhausted must not
penalize players for a period in which submissions could not execute.

Maintain last_fully_serviced_tick, last_observed_tick and monotonically
increasing service_generation. BEGIN_TICK and every mutating procedure call
invoke ensure_service(T). On first invocation at T:

- If the previous ledger tick equals last_fully_serviced_tick, continue.
- Otherwise increment service_generation and emit SERVICE_GAP.
- Set last_observed_tick=T. Repeated calls at T do nothing.
- END_TICK also invokes ensure_service(T), processes bounded work, and only
  after successful completion records last_fully_serviced_tick=T.

This detects a skipped END_TICK even when BEGIN_TICK previously ran.
It does not prove that every possible user call within a serviced tick could
execute. A partial-tick reserve outage repaired before END_TICK can escape
heartbeat detection. Before paid activation, prove and enforce a reserve
runway covering the pinned Core's maximum per-tick call load and hashing,
and test that interruption scenario. Without that protection this mechanism
must not be advertised as complete outage forgiveness; it fails the launch
availability gate. No off-chain operator judgement fills the gap.

On initial deployment initialize the heartbeat from the current tick and
explicitly exempt that construction tick from the missing-predecessor check.
Pin/test epoch-boundary tick successor semantics. Until that is demonstrated,
paid activation is blocked. A jump conservatively causes a service gap; the
website cannot assert continuity based only on its own wall clock.

Every offer/contest/cup captures its generation. A mismatch before an
unfinished result is finalized voids it with the predeclared refunds, no rating
or player fault. Cleanup is bounded/lazy; mark generation first so old objects
cannot act or match while awaiting cleanup. Already finalized results/credits
remain immutable. Old cup generation aborts the entire cup including pending
rake. This is an objective continuity mechanism, not discretionary loser rescue.

If the chain itself stops producing ticks, deadlines do not advance. Bot/site
or indexer downtime while the contract continues has no exception.
Admission-only maintenance stops new entries; it cannot rewrite active deadlines,
cancel valid results, withdraw escrow or choose who deserves a refund.

## 6. Errors, replay and evidence

Stable result codes:
OK, DUPLICATE, BAD_FRAME, BAD_OPCODE, BAD_BODY, BAD_AMOUNT, UNKNOWN_FIGHTER,
NOT_OWNER, NOT_OPERATOR, STALE_AUTH, FIGHTER_BUSY, COOLDOWN, FULL,
NONCE_CONFLICT, STALE, NOT_FOUND, EXPIRED, ALREADY_MATCHED,
INCOMPATIBLE, RULESET_RETIRED, WRONG_PHASE, LATE, ALREADY_COMMITTED,
BAD_STATE, BAD_COMMITMENT, BAD_PLAN, ALREADY_REVEALED, TERMINAL,
SERVICE_VOID, TRANSFER_FAILED.

An error must include operation/target/code and affected amount treatment.
Do not return OK before state and credit changes are durable.

Expose compact state and emit bounded events with event_seq u64, tick, type,
IDs, old/new state digests, accepted request digest and result. Round-resolved
evidence includes both canonical reveal plans/salts, executed-beat count and
the resulting mechanical state. Public readers independently reconstruct
the detailed [combat trace](combat.md). A trace URI is optional convenience.

Maintain an append digest:
SHA256("qdojo/combat/event/v1\0" || previous_digest[32] ||
event_seq u64 || event_type u16 || canonical_event_body).
Canonical event bodies MUST be frozen alongside the ABI before contract port;
do not hash in-memory structs or arbitrary exported JSON.

Retain a bounded event ring and current per-fighter/contest summaries. Export
full history with raw confirmed transactions through redundant indexers. Chain
inputs establish content; archival availability is a separate operational
requirement. Missing evidence is REPLAY_UNAVAILABLE, never VERIFIED.
Indexers cannot invent an unrevealed plan. Historical salts are public only
after reveals. Don't publish signed provenance for new docs using old hashes.

## 7. Bounds and validation

All IDs/nonces u64; round u8 0..2; auth versions u32; tick arithmetic uses
checked u64 internally even if Core exposes narrower ticks; no silent wrap.
All QU intermediates use checked signed 64-bit with nonnegative validation.
Maximum stake and cup size ensure multiplication fits; reject overflow first.

Candidate fixed capacities: 1024 fighters, 2048 admitted signer/credit accounts,
64 waiting offers, 16 active fights, 4 cups of at most 16 entrants, event ring
2048 records. Account/credit slots are reserved before accepting funds.
Keep enough settlement slots for all admitted contests. Eviction must never
remove positive credits or live locks. Export/history capacity is not permission
to overwrite financial liabilities.

Per tick: process at most 16 active fights, each at most six beats on resolution;
matching bound in [matchmaking.md](matchmaking.md); cup processing capped by
four cups/sixteen entrants each. Skip empty work. Cost/state size gate is
mandatory; these capacities are candidate ceilings, not measured capacity.

## 8. Implementation boundary and conformance checklist

Before the contract implementation milestone is complete, deliver generated
ABI tables and vectors for ALL user calls, query returns, admin descriptors
and canonical events. This is mechanical elaboration of the above semantics;
do not choose missing economic or authority policies in the encoder.

Administration may register reviewed asset IDs, create immutable cup descriptors
with pre-funded sponsorship, retire new admission to a ruleset, and publish
future configuration profiles under the deployment's authorized governance.
It cannot change accepted profiles, override combat, redirect credits or mint
a championship result. Actual issuer/governance keys and native procedure
indices belong to the release manifest and need explicit release authorization.

Conformance must include truncated/padded/oversized inputs, boundary integers,
same-tick commit/reveal/expiry, missed callbacks, reserve exhaustion/recovery,
direct vs nested callers, attachment refunds on retries, withdrawal failure,
cross-network/contract/fight/state replay, transfer handover and independently
computed SHA-256 commitment bytes. Freeze fixture input/output hex before
implementing native signing adapters. The legacy signer remains unchanged.
