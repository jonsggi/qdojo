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

## Not modelled yet

Latency races between equal fighters at the tick level, lost commits,
solver timeouts, LLM cost per round, a real sweeper strategy with several
identities, rake, fee scaling per belt, seasons.
