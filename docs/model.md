# The dojo's mechanics, modelled

House-side notes. `qdojo house model` runs a cohort of fighter archetypes
through the real evaluator, the real ladder and the real bond rules, so
every number below is what the settlement code would do, not an
approximation of it. Rounds cost microseconds; use replicates and sweeps.

## Formulas worth having in your head

- **Pot.** `pot = seed + carry_in + S`, where `S` is the counted stakes and
  `seed = min(cap, S · m)` with match rate `m = match_bps / 10000`.
  With full tables the cap binds, so matching saves little; with thin
  tables it is the whole difference between paying for an empty room and
  not.
- **House cost per round** `= seed − rake + NPC stakes`. NPC stakes are house
  money that passes through the pot to the winners; they are the price of
  a table that is never one short. They dominate: in the baseline below
  the house's own seed costs ~4,500 and the NPCs another ~2,700 per round.
- **Sweep bound.** Under stake matching a lone fighter facing only NPCs can
  never take out more than `(1 + m) · own stake + NPC stakes` per round,
  which is why the NPC stakes must be counted as cost, not as pot.
- **Ladder as a random walk.** At your own belt the points drift per round
  is `d = 2·p_win + p_solve − p_fail`. With promotion at +3 the expected
  rounds to promote is about `3 / d` when `d > 0`; with `d < 0` you demote
  in about `3 / |d|`. A fighter that wins its belt every time is out of
  it in two rounds; one that solves without winning needs three.
- **Bond.** Holding `b = bond_bps / 10000` of a win for `k` further fights
  means a fighter who leaves after one win keeps `1 − b` of it and the pot
  gets `b`. It does not change house cost; it changes who keeps the money
  and how long fighters stay.
- **Podium.** 5:3:2 over the first three correct commits cuts the top
  solver's share of the pot from 100% to 50% before bonds and 25% after a
  50% bond. It does not change the pot or the house cost.
- **Two pots.** With senseis at the table the pot is settled as two:
  `belt = carry_in + min(cap, S_belt · m) + S_belt` for the fighters at the
  belt and `sensei = S_sensei` for the seniors, each paid to its own solvers
  under the payout mode, each raked at the rate `r`, both leftovers carried
  into the next round's belt pot. The seed matches at-belt stakes only, so
  a table of seniors costs the house nothing, and a sensei alone in its pot
  can win back at most `(1 − r)` of its stake.

## Baseline, current sparring rules (2026-09-16)

Podium, 1:1 matching with a 5,000 cap, 50% bond for 3 fights, ladder on,
fee 1,000, min 3 players, 200 rounds, 8 replicates, default cohort
(2 sum specialists, 4 pure LLMs, 2 shell agents, 3 evolving tool-makers,
3 house NPCs).

| measure | value |
|---|---|
| house cost per round | ~7,280 (of which NPC funding ~2,730) |
| average pot | ~19,750 |
| top solver's share of a pot | 0.37 |
| Gini of net across fighters | 0.34 |
| largest single fighter's share of all earnings | 0.17 |
| promotions / demotions per 200 rounds | 56 / 41 |
| void rounds | 0 |

Per archetype, net per round: agent +1,330, evo +790, LLM +530,
specialist −80, NPC −1,000 (by design).

## What the model has taught us so far

1. **The ladder empties the low tables.** Within 25 rounds every real
   fighter is orange or above. White and yellow are then NPCs plus
   newcomers. Without house-funded NPCs 113 of 200 rounds were void for
   lack of a quorum. NPC funding is therefore not a sparring convenience
   but a permanent cost of the design, and it should scale with the number
   of low tables, not with the number of fighters.
2. **The top belt fills up.** Blue holds; there is no way out of it, so the
   strong fighters accumulate there and blue tables carry most of the
   money. Either a black belt with harder riddles and a bigger fee, or
   seasons that reset the ladder, or fees that scale with the belt.
3. **Matching saves ~10% at full tables, everything at empty ones.** The cap
   binds when six or more seats are bought. The saving is the no-show
   protection, which is exactly what it was for.
4. **Podium and bonds do what they were meant to do and nothing else.**
   Top share of pot: first-wins 0.99, podium 0.68, podium + 50% bond 0.34.
   House cost unchanged. Promotions barely change.
5. **Entering everything is a losing strategy for a specialist.** A sum
   bot that sits down at every table loses four stakes for every white
   win. The strategy hook exists for exactly this; the model's `enter`
   can be given per belt to see the difference.

## Gate options, live-calibrated cohort (2026-09-16, 150 rounds × 6)

| gate | season | house cost / round | dead tables of 150 | top share | Gini |
|---|---|---|---|---|---|
| strict (own belt or above) | none | 7,092 | 58 | 0.35 | 0.35 |
| strict | reset every 50 | 7,563 | 46 | 0.33 | 0.34 |
| soft (one belt below allowed) | none | 7,663 | 46 | 0.31 | 0.40 |
| soft | every 50 | 8,188 | 31 | 0.29 | 0.39 |
| handicap (any table, stake × 2^gap) | none | 9,973 | 0 | 0.25 | 0.54 |
| handicap | every 50 | 9,994 | 0 | 0.25 | 0.54 |

A "dead table" is a round where only house fighters sat down. Under the
strict gate more than a third of all rounds are dead once the cohort has
climbed. The soft gate and seasons help but do not fix it. The handicap
keeps every table alive but lets strong fighters farm the low tables
anyway, because a bigger stake comes back with the win, hence the Gini.

**The sensei seat — measured, then built (2026-09-16).** A promoted fighter
may sit below its belt: it pays the fee, wins back at most its own stake,
earns no belt points, and still banks the round toward its bond release.
Priced against the other gates on the live-calibrated cohort with the NPCs
removed (150 rounds × 6, 20% rake):

| gate, no NPCs | rounds void for want of players | Gini of net |
|---|---|---|
| strict | 100 of 150 | 0.49 |
| soft (one belt down) | 76 | 0.54 |
| handicap (stake × 2^gap) | 0 | 0.78 |
| **sensei** | **0** | **0.51** |

The sensei seat is the only gate that keeps every table running *and* keeps
inequality at the level of the strict ladder. The handicap also fills the
tables but lets strong fighters farm the low belts, because their larger
stake comes back with the win. On that evidence the NPCs were retired: their
whole job was filling tables for a quorum, and senseis now do it for free
while the NPCs cost ~2,000/round and won nothing.

## Two pots for the sensei seat (2026-09-19, 150 rounds × 6)

The live dojo showed what the sensei cap does with a cohort that has all
climbed: rounds 112-118 were seven blue senseis at white to green tables,
every winner capped at 1,000, and the seed the house matched on their stakes
went into a pot no one at the table could win. The carry went 7,600 →
53,700 in seven rounds and emptied only at blue, onto the strongest fighter.
Issue #10 replaces the cap with two pots: the belt pot (seed + carry +
at-belt stakes) for the fighters at the belt, the sensei pot (the seniors'
stakes, no seed, no carry) for the seniors. Priced before it was built, as
the seat itself was.

**The model now runs the house's own settlement for the sensei seat.** With
the sensei gate the model's round carries the belt and `sensei = true`, so
`round.evaluate` seats the seniors as senseis and `round.settle` applies the
money rule; the copy of the cap the model used to carry is gone. That copy
had run *after* the bond was held, so it let a sensei keep more than the
house actually pays, and the sensei figures in the gate section above are
too kind to the cap: through the real engine the cap reads Gini 0.78, not
0.51. The cap column below was measured with the engine as it was before
this change, the two-pot column with it, on the same seeds.

Run parameters: the live-calibrated cohort from `apps/web/data/fighters.json`
(24 fighters with three or more rounds; the five NPCs dropped, 19 remain),
gate `sensei`, 150 rounds × 6 replicates, seeds 1-6, podium, 20% rake split
60 / 10 / 30 (house / dev / shareholders), 50% bond for 3 fights, fee 1,000,
min 3 players, ladder on, no season. Every fighter sits at every table it
may (entry appetite 1.0, the calibration has no other). Two seed settings:
a 5,000 cap matched 1:1, and no seed. "Net per sensei seat" is what a seat
taken below one's belt returned, gross of the bond, less the stake.

| measure | cap, seed 5,000 | two pots, seed 5,000 | cap, no seed | two pots, no seed |
|---|---|---|---|---|
| house cost / round (seed − rake) | 3,022 | **−276** | −1,622 | −1,639 |
| house net / round (after dev and shareholder shares) | −3,813 | **−532** | | |
| average carry in | 15,928 | **594** | 4,784 | 206 |
| carry at the end of the run | 0 | 177 | 307 | 0 |
| Gini of net | 0.78 | 0.81 | 0.87 | 0.86 |
| top solver's share of a pot | 0.09 | 0.19 | 0.11 | 0.20 |
| largest fighter's share of all earnings | 0.24 | 0.19 | 0.22 | 0.22 |
| dead tables / void rounds of 150 | 0 / 0 | 0 / 0 | 0 / 0.2 | 0 / 0 |
| sensei seats per round | 6.5 | 6.7 | 5.2 | 5.3 |
| net per sensei seat, whole cohort | −655 | **−201** | −583 | −201 |

Per fighter, net per sensei seat (cap → two pots, seed 5,000): EVO-G31
−324 → **+345**, EVO-QWEN −592 → +53, EVO-DS −538 → −32, EVO-DS3 −641 →
−101, EVO-DS2 −590 → −103, EVO-GEM2 −671 → −151, EVO-GEM −677 → −374,
RYUBOT −835 → −356, the LLM agents (KEN-2, GEM-LITE, PI-AGENT, QWEN-AGENT,
GEM-2) −800 to −950 → −600 to −790.

What it says:

1. **The ratchet is gone.** Under the cap a round opened with 15,900 of
   carry on average, because the seed matched the seniors' stakes into a pot
   the seniors could not win, and it emptied only at blue. Under two pots
   the seed matches at-belt stakes alone: the average carry in is 594, and
   the house is 3,300 per round better off on the same tables. At a 20%
   rake it is now ahead on seed versus rake (−276) and at −532 after the
   dev and shareholder shares, against −3,813 under the cap.
2. **A sensei seat is a fair game among peers, minus the rake.** Net per
   sensei seat is −201 on a 1,000 stake at 20% rake, which is the rake and
   nothing else: the pool returns what went in. Under the cap it was −655,
   strictly negative for everyone, break-even at best. Whether the seat is
   worth taking now depends on who else is sitting: the strongest solver
   in the cohort (EVO-G31, 0.92 at white, 0.91 at yellow) makes +345 a
   seat, the second tier is about break-even, the weaker seniors lose. That
   is the shape a fair game should have, and it closes the phase-two item
   ("make the sensei seat worth taking"). Caveat: the cohort sits at every
   table; with EV-driven entry the losing seniors would stay away and thin
   the pool, which the model does not yet do (see below).
3. **Inequality does not move; the top win does.** The Gini of net is 0.78
   → 0.81, within noise of each other and set by the cohort's spread of
   skill. The top solver's share of a pot doubles (0.09 → 0.19) because the
   best sensei win is no longer one stake; it stays below the strict gate's
   0.35. The largest fighter's share of all earnings falls (0.24 → 0.19):
   the carry that dumped onto the blue tables used to go to one fighter.
4. **The seed has become nearly irrelevant to these tables.** Without any
   seed the two-pot numbers barely move (−201 a seat either way; house cost
   −276 → −1,639), because there are few at-belt stakes to match once the
   cohort has climbed. The seed taper the rake section asks for can start
   sooner than planned; what the seed still buys is a newcomer's first
   tables.
5. **The carry backlog is left standing.** The 53,700 the cap built up is
   belt money and is paid to the next at-belt winner in full: no cap, no
   decay. The model gives no reason to touch it -- under two pots it cannot
   grow again (an all-sensei table adds no seed and pays its own pot), and
   a jackpot at the low tables is the strongest reason a newcomer has to sit
   down.
6. **The teaching fee** the roadmap sketched as a way to pay senseis for
   liquidity is no longer needed to make the seat rational; the seniors now
   pay rake and can win. Worth re-deciding rather than building.

Not answered here: EV-driven entry (whether a seat is *taken* when it is
worth it), same-tick ties among identical bots, and coordinated senseis
sharing a solver, which under two pots would farm each other, not the
beginners.

## The rake, and whether the house can pay for itself (2026-09-16)

The rake is split three ways in basis points of the rake: house (treasury /
shareholders' retained share), a dev/team cut, and a shareholder pool paid
out via QUtil. Modelled at a 60 / 30 / 10 split (house / shareholders / dev),
200 rounds × 6, default cohort.

**A rake alone does not save the house.** With today's design (5,000 seed
per round, five funded NPCs), even a 30% rake leaves the house at
−3,779/round. The rake is a slice of the stakes; the seed and the NPC
funding are much larger and fixed.

Isolating the drains at a 20% rake:

| seed | NPCs | house net / round |
|---|---|---|
| 5,000 | yes (today) | −4,119 |
| 0 | yes | −1,998 |
| 5,000 | no | −3,652 |
| **0** | **no** | **+800** |

So the house is a net payer because of two launch subsidies, not because
the rake is too small:

- **The seed costs ~3,650/round.** It is onboarding money that makes early
  pots worth entering. It must taper toward zero as real stakes grow; it is
  not a steady-state feature.
- **The NPCs cost ~2,000/round and win nothing.** They are a pure conduit
  from the house to the winners. Their only job was to fill tables for a
  quorum, which a real cohort now does. Drop them, or keep the barest
  minimum only to guarantee a lone newcomer a table.

**At maturity — no seed, no NPCs — the rake is real revenue and positive:**

| rake | house / round | shareholders / round | dev / round |
|---|---|---|---|
| 10% | +402 | +70 | +23 |
| 20% | +800 | +132 | +44 |
| 30% | +1,151 | +184 | +61 |
| 50% | +1,830 | +258 | +86 |

The recommendation: keep the seed and NPCs only as a launch subsidy with an
explicit taper, run a rake from day one (20% is a reasonable start, split
house/shareholders/dev), and expect the house to cross into profit once the
seed is off and tables fill with paying players rather than NPCs. A house
share asset issued on Qx (the bot-share machinery, reused) receives the
shareholder pool via `qdojo house distribute-shareholders`.

## The entry fee as a controller (2026-09-19)

The buy-in was the one unpriced number in the dojo: `--entry-fee 1000` at
every belt since round one. Issue #9 proposes pricing it from published
data, per belt: the next fee follows the occupancy of the belt's own last
few tables, bounded below by a floor and above by the fair-game fee. This
section is the model run before the wiring, the way the sensei seat was
done. The rule is in docs/spec.md §5 and the exact inputs in docs/api.md.

Per belt, over the last `K` settled or void rounds at that belt:

    occ  = mean entrants                  void rounds count with their real number
    tgt  = min_players + headroom
    fee' = fee · (occ / tgt)^α            held within fee / clamp .. fee · clamp
    fee  = max(floor_b, min(fee', f*))    then three significant figures
    f*   = seed_cap / (tgt · ρ)           the fee at which the seed exactly refunds the rake

`f*` is where the average fighter, with share `1/n` of the winners' pot
under podium, breaks even; below it every seat is +EV before any skill,
and `f* − fee` is the subsidy per seat. With today's numbers (5,000 seed,
five seats, 20% rake) `f* = 5,000`; the fee is 1,000.

**Two things the model had to learn first.** Its fighters used to sit
down at any price, which makes a fee loop meaningless. `--demand ev` makes
a fighter enter only when its own expected value at the announced fee is
non-negative: it solves with its calibrated probability and shares the
winners' pot with the other expected solvers at a table of `tgt`; a
sensei, who can win back at most its stake, sits only while it has a bond
to release; house fighters sit regardless. And `--refill` lets an owner
top a broke fighter back up to its starting purse, which is what happens
in practice and the only way to see where the loop settles rather than
where the purses run out. Both are assumptions and are reported as such.

**Baseline, reproduced today.** Live-calibrated cohort from
`apps/web/data/fighters.json` at 119 rounds (19 named fighters with three
rounds or more; the five NPCs left out unless said), sensei gate, 20% rake,
5,000 seed matched 1:1, podium, 50% bond for 3 fights, min 3 players,
150 rounds = 30 tables per belt, 6 replicates:

| run | void | house cost / round | avg pot | Gini | note |
|---|---|---|---|---|---|
| strict gate, NPCs, rake 0, everyone sits | 0 | 7,764 | 20,337 | 0.35 | the gate table's first row read 7,092 / 0.35 on 09-16 |
| sensei, no NPCs, rake 20%, everyone sits | 0 | 2,912 | 19,122 | 0.75 | the sensei row read Gini 0.51 |
| the same, `ev` demand, fixed 1,000 | 0 | 3,376 | 13,395 | 0.59 | the weak stay home: the pot shrinks, the house pays more |
| the same, `ev` demand, refill, fixed 1,000 | 0 | 3,333 | 13,619 | 0.49 | the comparison basis for everything below |

The cohort has 55 more rounds of history than on 09-16 and is stronger,
which is why the reproduced rows differ from the dated ones. Every number
below is against these rows, on the same code.

**The controller at its defaults** (α 0.5, K 8, headroom 2, clamp 1.5,
floor 100, start 1,000):

| run | void | house cost / round | avg pot | top share | Gini | final fee w / y / o / g / b | reversals in the last 20 tables | subsidy / seat |
|---|---|---|---|---|---|---|---|---|
| fixed 1,000, refill | 0 | 3,333 | 13,619 | 0.13 | 0.49 | 1,000 everywhere | 0 | — |
| **auto, refill** | 0 | **−471** | 33,796 | 0.17 | 0.36 | 5,000 / 4,850 / 4,090 / 1,950 / 5,000 | 0.2 / 0.5 / 1.3 / 0.0 / 0.0 | 420 / 520 / 830 / 1,570 / 400 |
| fixed 1,000, finite purses | 0 | 3,376 | 13,395 | 0.13 | 0.59 | 1,000 everywhere | 0 | — |
| auto, finite purses | 5 | 2,027 | 17,263 | 0.17 | 0.77 | 620 / 510 / 740 / 260 / 2,310 | 0.2 / 0.0 / 0.3 / 0.0 / 0.5 | 2,400 / 2,500 / 2,500 / 2,900 / 1,800 |

The trajectory of one run with refill, as (fee, entrants) per table at the
belt:

    white  (1000,14) (1500,11) (2250,8) (3340,7) (4720,7) (5000,5), then 5,000 for the
           remaining 25 tables at 4-7 entrants, one dip to 4,870 for four tables
    blue   (1000,13) (1500,13) (2250,12) (3380,12) (5000,9), then 5,000 at 9-11 entrants
           for every table after, all 80 of them in a 400-round run
    green  (1000,9) (1340,9) (1800,7) (2320,8) (2980,7) (3770,5) (4620,6) (5000,6) (5000,3)
           (5000,3) (5000,5) (5000,5) (5000,4) (4810,4) (4560,3) (4140,4) (3640,5) ... (1790,4)
           at table 30; in the 400-round run it reaches the floor at table 63 and stays
           there at 3-5 entrants a table

What it says:

1. **The fee climbs to `f*` in five tables at every belt and stops.** At
   1,000 a 5,000 seed on five seats makes any fighter with a solve
   probability above a third to a half a +EV entrant, so nine to fourteen
   sit down and the fee rises by the clamp each table until the ceiling.
   That is the issue's "+800 per seat" seen from the other end: the
   controller's first job is to eat the subsidy, and the ceiling is what
   stops it. With the population held steady the house is paid 471 a
   round instead of paying 3,333, the pot is 2.5× larger, and the Gini of
   net falls from 0.49 to 0.36, because a seat is no longer free money
   for whoever is strongest.
2. **It settles; it does not oscillate.** Reversals in the last twenty
   tables are 0 to 1.3 per belt; white and blue sit on `f*` with none.
3. **The belt shape is discovered, and it follows the population, not the
   difficulty.** Blue, where 13 of 19 fighters end up, holds `f*` for 80
   tables at ten entrants. Green, which the ladder empties, drifts from
   5,000 to 1,790 in 30 tables and ends on the floor with four entrants a
   table: a quorum, one short of the target, and no price brings a fifth
   because there is none. Yellow and orange drift down as fighters promote
   out and back up as senseis with bonds arrive. With finite purses every
   belt drifts down as fighters go broke; that is the purse, not the
   price, and the reason the finite-purse rows show 4-20× spreads.

**The carry must not be in `f*`.** The issue's break-even formula has
`seed + carry` in the numerator, which is right for one round's expected
value and wrong as a ceiling: the carry is last round's luck. With it in,
blue reversed 11.5 times in 20 tables and swung 5,000-8,000 while nine
fighters sat down at every one of them; the fee was chasing no-winner
rounds, not demand. Without it: 0 reversals, 5,000 flat. A one-seat
deadband did not help (10.7). So `f* = seed_cap / (tgt · ρ)`, and the
carry remains what it is, an extra subsidy visible in `carry_in`.

**The sweep** (refill on unless said; spread is max / min over the last 20
tables at the belt):

| knob | void | house cost / round | Gini | final fee w / y / o / g / b | reversals | spread | reading |
|---|---|---|---|---|---|---|---|
| α 0.25 | 0 | +194 | 0.39 | 4,950 / 4,360 / 4,240 / 1,700 / 5,000 | ≤ 1.3 | 1.0-1.7 | slower to the ceiling, otherwise the same |
| **α 0.5** | 0 | −471 | 0.36 | 5,000 / 4,850 / 4,090 / 1,950 / 5,000 | ≤ 1.3 | 1.0-2.9 | |
| α 1.0 | 0 | −442 | 0.40 | 5,000 / 4,540 / 3,760 / 950 / 5,000 | ≤ 1.0 | 1.0-11.6 | overshoots at the thin belt |
| K 4 | 0 | −358 | 0.38 | 4,860 / 4,570 / 3,790 / 1,380 / 5,000 | ≤ 2.7 | 1.1-3.7 | noisier; 2 void with finite purses |
| **K 8** | 0 | −471 | 0.36 | | ≤ 1.3 | | 5 void with finite purses |
| K 16 | 0 | −633 | 0.37 | 5,000 / 5,000 / 4,210 / 2,920 / 5,000 | ≤ 0.2 | 1.0-1.9 | smoothest, but 11 void with finite purses: slow to see a belt emptying |
| headroom 0 (tgt 3) | 0 | −3,091 | 0.35 | 8,330 everywhere | 0 | 1.0 | `f*` is 8,330 and every belt sits on it; 49 of 150 tables void with finite purses |
| headroom 1 (tgt 4) | 0 | −1,692 | 0.39 | 6,250 everywhere | ≤ 0.3 | 1.0 | |
| **headroom 2 (tgt 5)** | 0 | −471 | 0.36 | | | | 5 void with finite purses |
| headroom 4 (tgt 7) | 0 | +1,356 | 0.37 | 490 / 270 / 380 / 100 / 3,570 | ≤ 0.3 | 1.0-12.9 | a target no belt but blue can fill: the fee falls to the floor |
| clamp 1.2 | 0 | +172 | 0.39 | 4,810 / 4,100 / 2,970 / 1,590 / 5,000 | ≤ 0.7 | 1.0-3.3 | slower |
| **clamp 1.5** | 0 | −471 | 0.36 | | | | |
| clamp 2.0 | 0 | −471 | 0.42 | 4,970 / 4,570 / 4,120 / 2,450 / 5,000 | ≤ 1.0 | 1.0-3.4 | |
| floor 100 / 500 / 1,000, finite purses | 5 | 2,027 / 2,070 / 2,307 | 0.77 | the floor is where a draining belt ends | | | it never binds at a live belt |
| voids count, finite purses | 5 | 2,027 | 0.77 | 620 / 510 / 740 / 260 / 2,310 | | | |
| settled only, finite purses | **21** | 1,819 | 0.75 | 1,350 / 1,270 / 1,280 / 1,060 / 2,990 | | | the tables that do not fill are exactly the ones it no longer sees |

The choices, from that: **α 0.5, K 8, headroom 2, clamp 1.5**. The
headroom is the one that matters: the target has to sit a couple of seats
above the quorum, or noise voids tables, and below what the belt can
supply, or the fee falls to the floor. **Void rounds retarget**, as the
issue leaned: a table that did not fill is the strongest signal that the
price is above what the belt bears, and leaving it out censors the
controller upward (21 void tables against 5). **The floor is a fixed QU
number, not a fraction of `f*`**: without a rake there is no `f*` (the
live house runs none), `f*` moves with the seed the operator sets, and
the floor never binds anywhere but at a starved belt, where the question
is a population one and a number in QU is what an operator can reason
about. `--fee-floor 100`, or per belt as `white=100,blue=500`.

**What the seed does to it.** `f*` scales with it. Seed 2,000: fees settle
around 2,000 with 50-400 of subsidy per seat, house −408. Seed 10,000:
fees 6,500-10,000, subsidy 1,300-5,100, house +394. **Seed 0: there is no
ceiling** (`f*` is 0, below the floor, so the floor wins and only the cap
bounds the fee): fees 8,800-17,600, every seat −EV by 4,000-12,000, ten
tables void. The `f*` ceiling is a launch-subsidy device; it and a retired
seed cannot coexist, and the day the seed goes to zero is the day the cap
has to be the ceiling.

**No rake, which is the live house today.** `f*` does not exist. Without a
cap the blue fee reached 64,000 and ten tables were void; with
`--fee-cap 5000` every belt is bounded, none void, house cost 4,978
against 4,860 fixed. So the policy carries an absolute cap, and a house
without a rake must set one.

**The corollary does not ship.** `seed_cap = max(0, target_pot − tgt · fee)`
with `target_pot` on a round-count schedule:

| run | void | house cost / round | final fee w / y / o / g / b | subsidy / seat | seed retired at round |
|---|---|---|---|---|---|
| auto, target 10,000, no taper | 10 | −7,717 | 8,940 / 7,810 / 5,730 / 480 / 24,870 | −10,900 to +3,460 | never |
| auto, target 10,000, tapered to 0 over 100 rounds | 4 | −4,468 | 2,040 / 1,070 / 7,030 / 1,380 / 13,770 | −600 to −10,800 | 66 |
| fixed 1,000, the same taper | 0 | −395 | 1,000 everywhere | — | 55 |

The coupling the issue feared is real and runs the bad way: fee up, seed
down, `f*` down to nothing, ceiling gone, fee up. Seats end −EV by
thousands and one table in fifteen voids. A round-count taper on a fixed
fee retires the seed earlier, voids nothing and costs the house 395 a
round. The seed taper stays an operator schedule on `--seed`; the
controller keeps one loop.

**House fighters break it.** Under the strict gate with the five NPCs
funded at the fee, every belt pins at `f*` whoever else comes, because
the NPCs sit at any price, and the house then funds their stakes at
5,000: cost 17,969 a round against 5,492 at a fixed fee. `qdojo house
spar` refuses `--entry-fee auto` together with `--npcs`; they are retired
anyway.

**What the model cannot tell us.** Price cannot fix a population drought.
Green ends on the floor because the ladder promoted everyone out of it,
and the model has no newcomers, so whether a 100 QU green table brings
anyone in is not a question it can answer; that is the sensei seat's job
and, at the floor, the teaching fee's. The demand model is a stated
assumption: expected value from calibrated solve rates, while real bots
run `--max-stake` and strategies of their own. Owner refill is an
assumption. Not modelled: how fast bots react to a fee change (they read
it in LOBBY, so within a round), latency, the cost of an LLM seat at a
higher fee, and any deliberate attempt to move the price by abstaining.

To reproduce (the sweep tables are one `--sweep` each):

    uv run qdojo house model --calibrate apps/web/data/fighters.json --no-house-fighters \
        --gate sensei --rake-bps 2000 --rounds 150 --replicates 6 --demand ev --refill \
        --entry-fee auto
    uv run qdojo house model --calibrate apps/web/data/fighters.json --no-house-fighters \
        --gate sensei --rake-bps 2000 --rounds 150 --replicates 6 --demand ev --refill \
        --entry-fee auto --sweep fee_headroom=0,1,2,4

## Not modelled yet

Latency races between equal fighters at the tick level, lost commits,
solver timeouts, LLM cost per round, a real sweeper strategy with several
identities, seasons.

## Planned execution costs (2026-09-19)

The off-chain estimates above do not establish profitability of the eventual
contract or an oracle-based verifier. Include these recurring costs when
selecting the settlement architecture and launch parameters:

The current decision is hash-based settlement without oracle-dependent judging.
Contract execution costs apply to that design; oracle/EVM/proof expenses below
remain comparisons for deferred alternatives.

- Qubic contract execution and state hashing, including recurring tick hooks,
  failed/repeated calls and the reserve needed to keep the contract operating.
- Oracle fees per actual query attempt, with explicit retry limits and timeout
  cases; never assume every query yields a usable result.
- EVM execution, proof generation where applicable, and relay transactions if
  the EVM-oracle design is selected. Record foreign-chain fees in their native
  currency as well as a common unit using the rate at measurement time.
- House hosting/operations, fixed seed subsidies, other sponsored participation
  and any guaranteed cup contributions. Keep solver costs separately visible
  when assessing whether fighters would voluntarily participate.

Calculate available margin from the retained house share, after shareholder,
developer and applicable author allocations, rather than the total rake:

`house operating net = house rake allocation - author fees - seed/NPC support
                       - contract execution - oracle queries
                       - external verification/relay - allocated operations`

Use actual integer allocation/rounding rules in the model. Attribute allocated
operations consistently and do not subtract any fee twice. Keep registration
receipts, IPO/reserve funding, capital top-ups and sponsor contributions
separate from recurring regular-round revenue. Upfront execution-reserve
funding does not eliminate the recurring cost consumed from that reserve.

Illustration, not agreed launch parameters: five 1,000-QU entries at 20% rake
produce 1,000 QU total rake. With a 60% house allocation and an author fee of
10% of that allocation, the house retains 540 QU before operating costs.
The inspected EvmLogRead interface charges 1,000 QU per query, so even one
such query exceeds that round's retained rake by 460 QU before seed, contract
execution, EVM gas or hosting. See
[verification research](verification-research.md) for the pinned source.

Compare per-submission, per-round and validated batch settlement, using the
same participation assumptions. Report total costs for empty/expired rounds,
small tables, full tables, retries and failed verification, plus settlement
latency. Set explicit execution, query and retry budgets before choosing the
architecture. Batching is only a candidate: its completeness and proof rules
must be specified, and delayed payouts affect the game.
