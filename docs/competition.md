# Competition, progression and events

> **Purpose:** rating, belts, faults, seasons, duels and cups. \
> **Audience:** players and spectators who want the standings explained; contract reviewers. \
> **Status:** normative (combat-v1 candidate 1). Implemented in `combat/rating.py`, `combat/series.py` and the reference contract; running on the simulated chain in the demo arena. Replaces riddle-era progression and season scoring. \
> **Last reviewed:** 2026-09-26 (§3 demo qualification scaling, §4 duel accept filters, §5 demo cup prices and sponsorship cap)

Combat rounds and series fights are different: every fight has at most three dependent combat rounds.

## Contents

- [1. Rating and belts](#1-rating-and-belts)
- [2. Faults and admission cooldown](#2-faults-and-admission-cooldown)
- [3. Seasons and championship](#3-seasons-and-championship)
- [4. Standalone duels](#4-standalone-duels)
- [5. Cups](#5-cups)
- [6. Required event tests](#6-required-event-tests)

## 1. Rating and belts

Maintain lifetime combat rating and a separate rating for each season.
Both initialize at 1000. Lifetime rating never resets on season, owner,
operator or software change. Season rating initializes at 1000 each season;
it is used only for that season's championship standings.

Use this deliberately simple integer rating formula, not floating-point Elo.
For pre-fight ratings RA, RB and score SA=2000 for A win, 1000 draw, 0 loss:

```text
EA = clamp(1000 + 2*(RA-RB), 100, 1900)
raw = 32*(SA-EA)
delta = sign(raw)*floor(abs(raw)/2000)       # truncate toward zero
if delta > 0: delta = min(delta, RB, 3000-RA)
if delta < 0: delta = -min(-delta, RA, 3000-RB)
RA_new = RA + delta
RB_new = RB - delta
```

Range 0..3000; transfers are exactly zero-sum including at boundaries.
Calculate from both OLD ratings. At equal 1000, a win transfers 16;
at A=1200/B=1000, an A win transfers 9, an A loss transfers 22,
and a draw transfers 6 from A to B. No stake weighting.

Apply separately to lifetime and season ratings using their respective old
values. Snapshot them at fight creation. Each fighter's exclusive lock prevents
concurrent ranked updates. Assign the season by ranked START epoch. Late
settlement updates that stored season, not the season current at settlement.

Only ranked combat results and unilateral player forfeits update ratings.
Combat draws update rating. Double-fault and service void do not.
Duels, cups, free practice and NPC exhibitions never update either rating.

First ten completed ranked COMBAT fights are placement; forfeits/voids do not
advance the counter. All placement fights still use the same rating formula
and matchmaking rules. Show provisional white with numerical rating.

After placement:

| Rating | Belt |
|---|---|
| 0..899 | white |
| 900..1099 | yellow |
| 1100..1299 | orange |
| 1300..1499 | green |
| 1500..1799 | blue |
| 1800..2099 | brown |
| 2100..3000 | black |

This replaces the old +2/+1/-1 belt points and difficulty-table gating.
Belt is a display derived from rating; it changes no combat stats, stake,
action access or purse entitlement. No sensei payout cap.

## 2. Faults and admission cooldown

One missing required commit/reveal gives that fighter one protocol fault and
a 240-tick cooldown from contest termination. Double fault applies to both.
Same request replay or an invalid attempt later corrected in time is not a
terminal fault. Service void is not a player fault.

Record rolling last-epoch fault counts and expose them. Three terminal faults
within an epoch disable ranked admissions for the remainder of that epoch;
duel/cup check-in still observes the ordinary 240-tick cooldown. This rule
does not override an already accepted contest or erase escrow.

Persist fault counts with the fighter through transfers. Bot defaults stop
autonomous entry after one fault, independently of contract cooldown.
A slow model, lost local salt or local disconnect follows player timeout rules.

## 3. Seasons and championship

A season spans four consecutive Qubic epochs from a manifest start epoch.
No volume-based 3/2/1 solve points remain. Rank eligible fighters by season
rating, then number of distinct opponents defeated in completed combat,
then completed combat wins. Money/stakes do not weight any criterion.

Qualification requires all of:

- At least 12 completed ranked combat fights in the season.
- At least 4 distinct independently registered opponent fighters.
- Combat wins against at least 3 distinct opponents.
- At least 3 completed ranked combat fights in the season's final epoch.
- Placement complete, no current admission suspension.

Forfeits, voids, duels, NPCs and cup wins do not satisfy these counts.
Known common-owner/operator opponents are already barred by matchmaking.

**Demo arena: thresholds scale with the field.** In a small population the
best fighters have few opponents inside their rating window, and a fixed
four-distinct-opponent rule excluded exactly them (the 2026-09-25 audit: the
top two fought mostly each other and a 754-rated fighter took the title). The
demo profile (`devnet.QUALIFICATION`, `contract.Qualification(scale=True)`)
therefore sets the distinct-opponent threshold to 20% of the season's field
(fighters with a completed ranked combat fight), at least 2 and at most 4, and
the distinct-defeated threshold to one less, at least 1 and at most 3; the
12-fight and final-epoch rules are unchanged. With 20 or more fighters in the
field this is the specified rule. It is a standings rule, not contract state:
`season_standings` takes it as a parameter and `seasons.json` publishes the
thresholds each season used.
The per-pair two-rated-starts-per-epoch limit also applies to placement.
These are mitigations, not a claim to detect undisclosed coordinated ownership.

At season end stop assigning new starts to it, keep its records until all
pending starts settle. A maximum 1200-tick closeout interval starts on the first
tick of the next season. Any objectively unresolved service-fault start is
void under the protocol; a delayed indexer cannot extend the deadline. Then
freeze eligible standings. New season play proceeds independently.

A unique leader gets the champion honour and a separate transferable trophy.
If all three standings criteria tie, the tied leaders enter a no-entry-fee
championship playoff using the cup pairing/replay rules below. Seeding uses
frozen season rank, then fighter ID. It awards no additional rating/points.
If no fighter qualifies or the bounded playoff produces no winner, archive
NO_CHAMPION and award no trophy. Never mint an arbitrary winner to satisfy a
marketing promise of one champion.

Trophy ownership does not alter the archived winning fighter/operator or
give cash/rake rights. Lifetime records persist; each season has separate
counts and rating. Completed season records are never silently rewritten.

## 4. Standalone duels

A challenge names the specific opponent, ruleset/timing/fee profile, equal
stake per fighter, format and expiry. Challenger funds immediately and takes
DUEL_OFFER lock. Stake must be at least the smallest enabled paid tier and
at most spec.md's maximum stake; arbitrary integer amounts in that range are
allowed for named duels. Cup fees/sponsorship obey the same maximum single
amount, with cup minimum/fee explicitly advertised. Named defender must be idle, authorized and outside cooldown
to accept with the identical stake. Any belt gap is allowed with explicit
acceptance. Cancellation/expiry before acceptance refunds challenger.

Formats:

| Format | Early victory | Maximum fights |
|---|---:|---:|
| SINGLE | 1 win | 1 |
| BO3 | 2 wins | 5 |
| BO5 | 3 wins | 7 |

Draws add no wins. At the fight cap, compare accumulated wins; higher wins
takes the series even if early-victory threshold was not reached. Equal wins
is a series draw and stakes are returned with no rake. The extra two fights
in BO3/BO5 bound draw replacements. No additional stake is requested.

Each fight resets health, stamina, opening, guard streak and power. Next fight
begins on the tick after prior resolution. One fixed stake covers the entire
series; one final rake. Forfeit ends the whole series, even when the forfeiter
was leading. Double-fault returns stakes; counts both faults. Service void
returns stakes and invalidates the unfinished series; completed individual
fight traces remain public and explicitly nonsettling.

No duel changes rating, belts, season eligibility or season score. All money,
honours and battle records are mode-labelled.

**Accept filters.** Because a named duel has no rating gate, the defender's
owner decides what to accept, and a bot must let them
([matchmaking.md](matchmaking.md) §5). The demo bots decline a challenger
rated more than 200 above them, a stake above their duel limit, and a
challenger they have played at least 3 series against with a series score
below one third (their own head-to-head history), and they apply the same
filters before challenging: in the demo the arena only picks who challenges
whom, the challenger's bot decides, pays and records the series. In the 2026-09-25 audit
auto-accepting bots let one scout bot win 138 of 143 series. In the demo
arena duel stakes grow with the format (1×, 2× and 3× the tier-1 stake for
SINGLE, BO3 and BO5), so the single rake of a longer series still pays for its
fights ([economics report](economics-report.md)).

## 5. Cups

Candidate bounds: 4 simultaneous cups, 4..16 entrants per cup; manifest may
reduce these after cost measurement. Organizer locks a published descriptor:
ruleset, timing, entry fee, cup rake/split, funded sponsorship, registration
close tick, minimum/maximum entrants, pairing schedule and total expiry.
Descriptor and sponsor allocation cannot change after first registration.

An entry reserves its fighter until elimination, cancellation or cup completion.
One fighter per known owner/operator. Entry amount is exact. Registration and withdrawal are allowed only while tick < registration_close;
at END_TICK registration_close the roster locks. Withdrawal before
registration close returns the entry and loses its priority; after bracket
lock the entry is part of the prize. Additional sponsorship after first
registration is rejected in v1 to keep the guaranteed pool fixed.

If fewer than the minimum register, refund every entry and sponsor without rake.
At bracket lock, reserve gross entries/sponsorship and separately compute the
advertised net prize and pending cup rake. Pending rake is not paid until a
champion exists; it remains refundable on a whole-event service abort.

### Bracket

Candidate v1 deliberately uses deterministic rating seeding, replacing the
archived random-bracket sketch. This avoids an unspecified randomness service.
Sort entrants by snapshotted lifetime rating descending, then fighter ID
ascending. Let P be the smallest power of two >= entrant count.
Assign missing seeds as byes.

Generate seed positions exactly:

```text
positions = [1, 2]
while len(positions) < P:
    m = 2*len(positions) + 1
    positions = flatten([seed, m-seed] for seed in positions)
```

For eight: [1,8,4,5,2,7,3,6]. Consecutive slots are first pairings; winners
advance in bracket order. Publish roster, ratings, positions and digest.
No organizer-selected pairings or redraws. Seeding is manipulable through
rating/entry decisions; do not advertise it as random or manipulation-proof.

### Schedule and check-in

Early pairings are BO3; final is BO5. All fights use three-round combat.
Publish one 3000-tick window per bracket level. First level starts 120 ticks
after bracket lock; later levels start at fixed 3000-tick increments from
the previous level's actual start, including a permitted postponement.
Within a level, check-in is its first 120 ticks. Next tick starts checked-in
pairings, subject to the global 16-fight capacity.

Reserve one global active-fight slot per non-bye pairing for the entire
level, including the time between series fights/replays. Release unused slots
when that pairing finishes. Pairing reservations belong to the existing cup
lock, not a second independently spendable fighter activity.

At bracket lock, reserve capacity for the first level if available. For later
levels, attempt reservation at the previous level's END_TICK. Competing event
reservations are processed by increasing cup_id; ranked matches may use only
unreserved capacity. Reserve capacity for the level before taking check-ins. If capacity is not
available, postpone the ENTIRE level by 3000 ticks, at most once; emit the new
schedule before its check-in opens. If still unavailable, event service-aborts
with refunds. A fighter must not forfeit due to unavailable contract capacity.

Exactly one check-in: opponent forfeits pairing. Neither: both eliminated.
Byes advance without check-in or a fabricated win. A transferred fighter
may authorize its operator at the unchecked pairing boundary and checks in
with its current verified owner/operator; schedule remains fixed. If an
owner/operator is already represented by another surviving fighter, reject
check-in until that conflict is resolved before the deadline; there is no
refund or extra delay. Display this consequence before an asset transfer.
A timeout after play begins forfeits the pairing under protocol rules.

### Unresolved pairings and bounded replay

If BO3/BO5 ends tied, hold one replay within the SAME level window:
start it 120 ticks after the tied result. Replay is first to one combat win,
at most three fresh fights. Preserve original traces; replay winner advances.
If all three draw, eliminate both and mark UNRESOLVED_PAIRING. An empty
bracket slot gives the next opponent a bye. No random winner, higher-rating
tiebreak or organizer judgement.

All scheduled work must fit the level window with the selected timing profile.
Manifest validation rejects a profile where max series + replay + check-in
cannot fit. A contract-wide service fault aborts that cup; local player
disconnects do not. An event-wide absolute expiry is one extra 3000-tick
window beyond its latest permitted final level; reaching it aborts.

### Prize and abort

Final winner receives the advertised net prize; pending entry rake is then
allocated once. Sponsor funds are never raked. No per-pairing escrow/rake.
Known no-show/eliminated entrants have no individual refund after lock if a
champion is produced.

If the final has no surviving winner, or no actual combat fight was completed
in the whole event, abort without a trophy or rake. On whole-event abort return
ALL entry fees and sponsorship to original payers, including eliminated entrants.
Earlier pairings remain archived exhibition results with no rating changes.
Gross funds must have remained reserved to make these refunds possible.

**Demo arena cups.** Entry is twice the tier-1 stake and cup entries carry a
1,000 bps fee profile (twice the ranked rake), because a cup of eight plays
about eighteen fights for one set of entries. Every ranked demo bot may enter,
so the strongest ranked fighters meet the cup field. The house sponsors each
cup with 0.1× the tier-1 stake, except while one fighter has won more than 2
of the last 6 sponsored cups: a fixed script cannot keep capturing house money
(the audit's oni took 25 of 27 cups and 125,000 QU of sponsorship). These are
host choices in `live.EVENTS`, published in `economics.json`.

At a pairing boundary, a buyer inherits the reserved bracket position and next
schedule. Prize entitlement for the final is fixed to its check-in snapshot.
Ownership change cannot duplicate a seat or create a new entrant exemption.

## 6. Required event tests

Cover boundary rating truncation/clamping; side symmetry; draw rating changes;
placement not advanced by forfeits; season assignment across epoch change;
no season points from NPCs; shared-owner exclusions; transferred finalists;
non-power-of-two brackets; both no-shows; tied replay; event-capacity postponement;
abort after earlier eliminations; pending-rake refunds; duplicate finalization;
and no fees or trophy when there is no champion.
