# Automatic matchmaking

Version: combat-v1 candidate 1. Status: implementation specification.
Fight mechanics live in [combat.md](combat.md); money/identity in [spec.md](spec.md).

## 1. Public book and admission

The book contains funded offers. Joining authorizes an automatic compatible
match; there is no post-pairing accept/decline step. The engine uses the same
three-round fight for ranked matches, duels and cup pairings.

Offer fields:

| Field | Meaning |
|---|---|
| offer_id | Monotonic contract sequence, never recycled |
| fighter_id | Registered identity; exclusive activity lock |
| owner, operator, auth_version, payer, payout_recipient | Snapshotted authority and money destination |
| ruleset_digest, timing_profile, fee_profile | Immutable accepted terms |
| stake_tier, amount | Exact manifest tier and funded stake |
| rating | Confirmed combat rating at entry |
| max_rating_gap | Owner-authorized widening cap, 100..200 in candidate 1 |
| created_tick, expires_tick | Expiry is exclusive: matching requires tick < expires_tick |
| service_generation | Objective contract-service continuity generation |
| status | OPEN, MATCHED, CANCELLED, EXPIRED, INVALIDATED |

Initial development manifest: one tier at 1,000 QU, 64 total waiting offers,
16 simultaneous fights, matching interval 4 ticks, at most 4 new matches
per pass. These are hard test bounds; production values require cost results.
Full capacity rejects admission and returns the attached payment.

Default offer lifetime is 240 ticks; valid requested lifetime 40..1200 ticks.
Owner/operator can cancel before match lock. Expiry/cancellation returns the
original payer's stake as withdrawal credit. No queue rake.

All registration, owner/operator, payment, cooldown and activity-lock checks
happen before admission. No hidden increase in stake, credit line, repeated
entry, or default house-NPC opponent. There are no partial fills.

## 2. Compatibility predicate

Two offers are compatible at tick T exactly when ALL hold:

1. Both OPEN, nonexpired, current service generation, valid ownership/authority.
2. Distinct fighters; owner differs AND operator differs; neither is a house NPC.
3. Same network/contract, active ranked ruleset, timing profile, fee profile,
   currency and exact stake tier/amount.
4. Neither has any other reservation or active contest.
5. Absolute rating difference is within BOTH current windows.
6. This pair has fewer than two rated starts in the current epoch and its
   most recent ranked result ended at least 120 ticks ago.
7. Both are outside fault cooldown and have a reserved rating-update capacity.
8. A fight slot and bounded result/accounting capacity are available.

Window for offer O:
`min(O.max_rating_gap, 100 + 50*floor((T-O.created_tick)/40))`.
Windows are symmetric in admission: a long-waiting bot cannot override a
newly joined opponent's narrower window. Widening never changes stake or
rules. No arbitrary opponent ID filter in the ranked queue.

The per-pair epoch counter increments at match start, not settlement. It
prevents a reveal abort or quick forfeit from creating free repeated pairings.
An objective contract-service void reverses that start count exactly once.
Counters use sorted fighter IDs and epoch, with bounded storage retained until
all starts from that epoch have reached finality.

A fighter's rating cannot change while queued because its lock prohibits other
ranked matches. Ownership must still be rechecked at pairing. If QPI ownership
cannot be established, do not pair that offer; record the unavailable service
and permit cancellation. Do not treat an unknown owner as the old owner.

## 3. Exact ordering and work bounds

At END_TICK, after processing fight deadlines, run a matching pass when
`tick mod 4 == 0`. Operate only if at least two offers exist.

1. Snapshot OPEN offers sorted by increasing offer_id.
2. Revalidate at most 64 offers; expire/invalidate those no longer eligible.
3. For each remaining i in order, scan later unmatched j in order.
4. On the first compatible j, atomically remove/reserve both offers and create
   their fight; mark both matched in the snapshot; continue at the next i.
5. Stop after four matches or no remaining compatible pair.
6. An unmatched older offer does not block a younger compatible pair.

At most 2016 pair comparisons (64*63/2) per pass; matched pairs are skipped.
Do not perform an unbounded nested search or issue one transaction per pair.
Measure ownership lookup, comparisons, hashing and new-fight creation together.
If the bound exceeds the cost budget, reduce manifest capacity/throughput or
design a new indexed matcher and prove its equivalence before activation.
Do not silently change matching priority for performance.

Fight slot A/B is determined by fighter ID, independent of who queued first.
Start tick is the matching tick. Round-zero commit opens on the next tick.
Both locks and both escrow moves happen in the same successful operation.

## 4. Races and lifecycle

A cancellation transaction processed before pairing wins the race.
After pairing it returns ALREADY_MATCHED and cannot reclaim escrow.
Same-tick transactions follow confirmed chain order; this is an entry-order
rule, not a combat advantage. Expiry at T means unavailable at T even if
cleanup has not yet removed the record.

Repeated cancellation, timeout advance or identical request is idempotent.
Replacing an offer means cancel, then enter a new offer with a new ID and
priority. Updating a stale offer in place is forbidden.

A transfer detected before pairing invalidates the offer, unlocks the fighter
and refunds its original payer. Buyer must authorize and enter separately.
An objective service-generation change invalidates older offers with refund.
Public clients may trigger expiry/progress but cannot specify the selected
opponent or skip an earlier compatible offer.

Completed results release the fighter lock after accounting/rating is durable.
The bot may then choose to re-enter. There is no unlimited contract standing
order that spends earnings forever.

## 5. Autonomous budgets

The client scheduler needs independent owner-configured limits:

- Allowed tiers, maximum per-fight stake, maximum total escrow.
- Maximum committed stakes per rolling UTC day, never offset by wins.
- Maximum realized net loss per rolling UTC day.
- Maximum fights per session/day, cooldown between fights, stop time.
- Minimum available withdrawal/wallet reserve.
- Allowed modes, ruleset/timing digests, maximum rating gap.
- Stop after consecutive protocol faults (default one).
- Optional spending limit on external model/provider use.

Persist reservations before sending; retry with the same request nonce.
If state, balance, settings or a strategy process cannot be read, do not enter.
Never interpret an error as permission to spend. Existing AUD-005 applies.

Risk limits are owner controls, not promises of profitability. Account for
outstanding escrow conservatively when determining remaining budget.

## 6. Public UX and abuse boundaries

Show waiting fighter, rating/provisional marker, stake, current/max window,
expiry, ruleset and known affiliation. Show match-ready eligibility and reasons
for waiting. Do not promise a numerical wait estimate without observed data.

Provide separate actions: Ranked, Challenge fighter, Tournament, Free sparring.
NPC availability must not be presented as human queue liquidity. Selecting
free sparring never joins a paid queue.

FIFO compatibility reduces explicit opponent selection but does not remove
timed entry, collusion, transferred identities or hidden common ownership.
Paid registration is a participation credential, not a proof of personhood.
Monitor repeated pairing, forfeits, ownership clusters and abnormal rating
transfers. Do not claim these checks solve collusion.

## 7. Required scenarios

- Equal ratings/stakes match; unequal stakes or profiles do not.
- A=1000 waiting long, B=1180 just entered: no match until B's window reaches 200.
- Older incompatible offer does not block younger compatible offers.
- Two equally compatible candidates choose lower offer_id.
- Cancel before lock refunds; after lock does not.
- Expiry and match at the same tick cannot both succeed.
- Transfer between entry/pairing refunds original payer and creates no buyer entry.
- Duplicate requests create one offer, one lock, one liability.
- Pair counter/cooldown block immediate farming; service void reverses only its start.
- Full queue/active capacity rejects without taking funds.
- Four matches/pass cap is observed without losing remaining offers.
- House NPCs cannot enter ranked or satisfy championship participation.
