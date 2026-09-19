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

## Not modelled yet

Latency races between equal fighters at the tick level, lost commits,
solver timeouts, LLM cost per round, a real sweeper strategy with several
identities, rake, fee scaling per belt, seasons.

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
