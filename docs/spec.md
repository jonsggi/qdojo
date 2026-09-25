# Combat specification

> **Purpose:** scope, identity, money and cross-system invariants of combat-v1; the entry point to the normative set. \
> **Audience:** contract and protocol reviewers, implementers. \
> **Status:** normative (combat-v1 candidate 1, written 2026-09-21). Implemented and tested on a simulated chain with fake QU; **not deployed**. The strategic gates pass on held-out seeds ([validation-status.md](validation-status.md)); economics with real costs are not measured. \
> **Last reviewed:** 2026-09-25 (header, status and links; rules text unchanged)

## Contents

- [1. Authority and reading order](#1-authority-and-reading-order)
- [2. Product and terms](#2-product-and-terms)
- [3. Scope and retired mechanics](#3-scope-and-retired-mechanics)
- [4. Fighter identity and locks](#4-fighter-identity-and-locks)
- [5. Money and settlement](#5-money-and-settlement)
- [6. Authority, capacity and availability](#6-authority-capacity-and-availability)
- [7. Versioning and deployment manifest](#7-versioning-and-deployment-manifest)
- [8. Cross-system invariants](#8-cross-system-invariants)

## 1. Authority and reading order

The product pivots from riddle solving to autonomous simultaneous combat.
These documents replace the previous planned riddle release. The riddle game's
commands, exports and historic settlements remain available as Legacy, in a
namespace separate from combat.

| Document | Owns |
|---|---|
| [combat.md](combat.md) | Actions, resources, exact resolution and examples |
| [matchmaking.md](matchmaking.md) | Queue compatibility, ordering and reservations |
| [competition.md](competition.md) | Rating, belts, seasons, duels and cups |
| [protocol.md](protocol.md) | Bytes, hashes, deadlines, authentication and state machine |
| [api.md](api.md) | Bot interface, public data, replay and the combat CLI |
| [npcs.md](npcs.md) | Disclosed practice/exhibition policies and training randomness |
| This document | Identity, money, scope and cross-system invariants |
| [model.md](model.md) | Balance, exploit, economics and latency acceptance gates |
| [pivot-plan.md](pivot-plan.md) | Historical: the implementation packages P0–P8 |
| [roadmap.md](roadmap.md) | Dependencies and release sequence |
| [operations.md](operations.md) | Runtime, incidents and release checklist |
| [product-decisions.md](product-decisions.md) | Decisions and open deployment values |

Read this document plus combat, matchmaking, competition, protocol and API
before implementing a paid combat path. A summary
defers to its owning document. Fix contradictions between owning documents
before implementing the affected behavior. MUST/MUST NOT are requirements.
Candidate parameters are implemented as written in the prototype, then versioned
if validation changes them. Do not fill an unspecified behavior with old rules.

The [riddle archive](archive/riddle-v0/INDEX.md) explains legacy code and
evidence only. Never load a riddle message, balance or record as combat state.

## 2. Product and terms

Owners develop bots. Bots study public fights, select hidden action sequences
and adapt between three rounds. The contract computes combat and accounts for
the purse. The website replays the resulting trace.

- **Beat:** one simultaneous action per fighter.
- **Round:** six committed beats resolved as one bounded computation.
- **Fight:** at most three rounds; health/resources persist across rounds.
- **Series:** one, best-of-three or best-of-five fights; each fight starts fresh.
- **Contest:** a ranked fight, accepted duel series or tournament pairing.
- **Offer:** funded, expiring intent to enter matchmaking or a named duel.
- **Fighter:** persistent registry identity backed by a recognized asset.
- **Operator:** authorized bot signer; software runs off chain.
- **Ruleset:** immutable combat semantics and parameters identified by a digest.

A normal fight has eighteen possible beats, not eighteen submissions.
Target duration is 45–60 seconds after pairing; this is a validation target,
not a network guarantee. Show matchmaking wait separately.

AI is optional. Hand-coded policies, search, statistical models, self-play and
AI-assisted development are legitimate. No hosted bot execution, latency-based
damage, damage rolls or purchased combat stats exist in v1.

## 3. Scope and retired mechanics

Full release includes free training and analysis, combat SDK, public replays,
ranked automatic matching, duels, cups, four-epoch seasons, fighter registration
and ownership handover, trophies, direct contract settlement, autonomous limits
and accessible spectator playback. Contract comes after reference validation,
and before external paid launch. This is not a request to launch a money pilot.

Retire riddles/canonical answers, author fees, quorum tables, first-correct
and podium payouts, solve points, sensei seats/pots, stake matching, jackpots,
occupancy-priced entry, held-win bonds and difficulty-based belt gates.
Old bond/carry obligations remain legacy liabilities; they do not become
combat prize funds. Old simulation numbers do not establish combat economics.

Community work becomes training opponents, analysis tools, balance proposals
and cosmetics. Arbitrary submitted code never runs in the settlement contract.
Buffs, equipment, positions and extra ranked rulesets are deferred. The v1
power strike in [combat.md](combat.md) is an equal-access limited resource.

## 4. Fighter identity and locks

Use a 32-byte registry identifier, mapped to exactly one recognized indivisible
asset (issuer public key, asset name, one unit). Names alone are insufficient.
Never reuse identifiers. Resolve and test the actual Qubic asset representation
before paid registration; do not represent an unenforced JSON label as ownership.

Confirmed owner sets one operator with an increasing authorization version.
An accepted offer snapshots owner, operator, authorization version and payout
recipient. Recipient MUST equal the confirmed owner at acceptance.

Exactly one exclusive activity lock per fighter:
`IDLE | QUEUED | DUEL_OFFER | CONTEST | TOURNAMENT`.
Owning multiple fighters is allowed; known shared owner OR operator prevents
ranked pairing. Cups admit at most one fighter per owner/operator. Separate
identities do not prove independent control.

Owner/operator authorization changes require IDLE, or a TOURNAMENT reservation
between pairings before that pairing's check-in. After check-in authority is
fixed through that pairing. The tournament reservation is never released by
this exception. Owner can cancel unmatched
offers. Recheck ownership before matching or duel acceptance; a transferred
offer is invalidated and its original payer refunded, never silently redirected.

During an accepted contest, transfer preserves the snapshotted operator and
payout recipient until settlement. Buyer gains competitive control at that
boundary: whole series for a duel; pairing for a cup. Cup bracket position
and schedule follow the fighter; next check-in binds the new owner/operator.
No transfer pauses a cup. Final-pairing snapshot owner receives the cup prize,
even if the asset transfers during that pairing. Display these obligations.

Rating, history, faults and honours follow the fighter; solver software does
not automatically accompany an asset sale. A transfer cannot reset placement.
Legacy ranks are archived and do not become combat skill ratings.

Retain ten gifted founding fighters and expandable ordinary issuance.
Founding status is cosmetic/provenance only. Training/viewing/building require
no wallet or NFT. Prices, recognized assets, allocation and rights are launch
manifest decisions; implementation agents must not invent production values.

## 5. Money and settlement

All amounts are integer QU. Local zero-stake practice is separate from paid
queues. Exact payment only; reject under/overpayment and return the attached
amount without admitting the offer. Rates/recipients are fixed before funding.

Development fixture values, NOT authorized production pricing:

| Parameter | Value |
|---|---:|
| One ranked stake tier | 1,000 QU per fighter |
| Ranked/duel rake | 500 bps of paired stakes |
| Cup rake | 500 bps of entry fees |
| House / developer / shareholder rake allocations | 6000 / 1000 / 3000 bps |
| Subsidy, NPC funding, author fees, new bonds | 0 |
| Maximum single stake | 1,000,000,000,000 QU |

For equal stakes S:
`gross=2*S; rake=floor(gross*rake_bps/10000); winner_credit=gross-rake`.
Developer receives `floor(rake*dev_bps/10000)`, shareholders receive
`floor(rake*share_bps/10000)`, house receives the remaining rake.
Rounding belongs to house allocation; no rolling carry. Allocation bps sum
to 10000. Ranked and duel profiles may differ only when advertised in advance.

| Ranked fight / whole duel result | Money | Competitive treatment |
|---|---|---|
| Combat win or single-player forfeit | Winner gets purse less rake | Ranked rating; season qualification distinguishes play from forfeit |
| Combat draw / series tied at limit | Return each stake; no rake | Ranked combat draw updates rating |
| Both miss required deadline | Return each stake; no rake | Fault/cooldown for both; no rating |
| Unmatched expiry/cancellation | Refund original payer; no rake | None |
| Objective contract-service void | Return each stake; no rake | No fault/rating |

Single-player timeout forfeits the whole contest. Invalid reveals may be
corrected before the deadline; absence of a valid reveal at expiry is a fault.
Refusing to reveal a losing plan never grants a refund against a compliant
opponent. Stake escrow is also the non-reveal deterrent.

Cup advertised prize = sponsor contributions + locked entry fees - entry rake.
Keep the gross amount reserved and the rake pending until a champion exists;
event abort refunds gross entries/sponsorship under competition.md.
No per-fight rake, no rake on sponsorship, no bonds. Quorum failure returns
entries and sponsorship to original payers without rake. After bracket lock,
normal winner gets the whole prize. Aborts follow [competition.md](competition.md).

Terminal processing records one immutable result and credits withdrawals once.
Before/after every operation the available contract balance must cover:
`unmatched escrow + contest escrow + cup reserve + withdrawals + fee credits`.
Execution-reserve burns come from house earnings or explicit capital, never
from liabilities to players. Registration/sponsorship/operating income are
separate categories.

A recipient withdraws its whole current credit to its own identity. No redirect.
Zero is a no-op. Debit before transfer; check platform result; restore credit
on reported failure if rollback is absent. Prove semantics on the pinned Core;
do not assume EVM transaction rollback. Failed/repeated sends cannot pay twice.

The reference implementation runs on fake funds. A paid off-chain rollout is
not implied. Legacy money operations retain [existing audit gates](../audits/README.md).

## 6. Authority, capacity and availability

Contract state and confirmed actions determine the winner. No house signature,
oracle, bot-upload execution or website approval is required. Public clients
may query state and trigger permitted progress. Indexers/watchers are replaceable.

Bound queues, tournament sizes, active fights, expiry work and every loop.
Full capacity rejects new admissions and returns funds; existing contests
finish. Never evict a liability to make room.

A failed node/indexer read is unknown, not evidence of a missed submission.
Local bot/provider/site outages do not change on-chain deadlines. Objective
contract-service interruptions use the precise exception in
[protocol.md](protocol.md).

Verification requires confirmed inputs, commitment agreement, fixed ruleset
and independent replay against the result. Hashing a same-source JSON document
does not establish correct settlement. Display what was actually checked.

## 7. Versioning and deployment manifest

A fight/series/cup keeps its accepted rules through completion. Balance changes
produce a new ruleset digest and fixtures; never change in-flight parameters.
One active ranked ruleset per season. Stop new admissions on security retirement;
unfinished contests follow the predeclared objective void conditions.

Production activation requires a manifest with:

- Network identifier, deployed contract identity/index and pinned Core commit.
- Protocol/ABI digest and conformance fixtures.
- Asset registry, metadata/rights and verified ownership/delegation.
- Ruleset, timing profile, capacities and tournament bounds.
- Stake tiers, rake, recipients, registration prices and issuance policy.
- Measured execution/state costs, reserve policy and end-to-end timing.
- Season boundaries, replay export/retention and release version.
- Passed acceptance report and audit dispositions.

Missing production values keep paid admission disabled; local work continues.
Never default to guessed network, contract index, registry, signer or price.

## 8. Cross-system invariants

Required verification scenarios:

1. Swapping fighter slots swaps complete combat trace/result.
2. Valid reveal arrival order cannot affect combat.
3. Next round begins from the exact prior derived state.
4. One activity lock and authorization per fighter; transfer creates no extra seat.
5. Changing any commitment-bound field invalidates its reveal.
6. Accepted QU belongs to exactly one liability or earned allocation.
7. Settlement, retry, expiry and withdrawal are idempotent.
8. A unilateral non-revealer loses the contest to a compliant opponent.
9. Expired/transferred offers cannot match or consume rating eligibility.
10. Full/stale/malformed/rejected operations conserve funds.
11. Independent reference, browser and contract agree on frozen fixtures.
12. Legacy state cannot be accidentally loaded into combat.
13. Verification works without trusting the qdojo website.

Detailed fixtures and statistical requirements are in
[combat.md](combat.md) and [model.md](model.md).
