# Roadmap

## Phase zero, off chain — COMPLETE (2026-09-16)

Built and run: 30 live rounds across an 18-fighter cohort, 149 tests.

- [x] spec, wire protocol, lore, developer API (docs/api.md), modelling notes (docs/model.md)
- [x] pure core: hashing, payloads, round evaluation, settlement
- [x] chain layer: fake for tests, qubic-cli + indexer for real, indexer-lag safe
- [x] house CLI: lobby / publish / collect / settle / void / export / metrics / model / distribute-shareholders
- [x] bot CLI: init (seed + node discovery), bow, run with any solver, stats, shares, dividend, strategy hook
- [x] spectator page: lobby table, rounds, results, void, fighter profiles, eight halls of fame, hash verify
- [x] first live round (2026-09-15) and a full sparring run (68 rounds)
- [x] economics: stake-matched adaptive seed, lobby quorum, belts, bonds, podium, three-way rake
- [x] mathematical model calibrated against the live cohort; gate + rake + NPC findings (docs/model.md)
- [x] self-evolving tool-making fighters, LLM fighters on cheap models, house-funded NPCs

Deferred to phase one (the contract): pure-Python signing to drop the
qubic-cli dependency for bots; the sensei seat and the gate choice; belt
seasons; on-contract bond custody and shareholder claims. The economic
findings above are the brief for the contract's parameters.

## Phase one, the contract
- seats, auctions, inactivity eviction, NPC seats acting at tick boundaries
- commit and reveal inside the contract, pot and rake in state
- IPO of 676 shares, fees to shareholders
- proposal through GQMPROP

## Phase two
- belts as on-chain rank, avatars as Qbay NFTs (but see Sketches: title belts, earned)
- community riddles with an author stake and cut
- parimutuel spectator pools (Quottery's model), after legal review
- oracle-fed riddles once a second oracle interface exists

## Sketches — recorded, not scheduled (2026-09-17)

Three ideas from one brainstorm. They turned out to be one idea, so they are
written together. Nothing here is decided and nothing is costed.

**The face-off.** A fighter proposes a duel to another and names the buy-in;
the other enters or declines. Mechanically a duel is a table with
`min_players=2` and an invite list of one — same ENTER / COMMIT / REVEAL,
same rake, same evidence document, almost no new machinery. Both sides
escrow before the riddle exists, as always. A challenge expires after a set
window and an expiry is a decline. If both reveal correct, the earlier tick
wins. If neither solves, both are refunded less the rake: the house never
profits from a burn, but a challenge is never free either.

The ladder gates it exactly as it gates tables: **you may challenge at your
belt or above, never below**, and a challenge downward is refused
(`outranked`) and refunded. A higher belt may still *offer* a duel downward
on sensei terms — wins back at most its stake, no points move either way.

From that gate the rest follows without a single new rule. The duel carries
the **defender's** belt, so the challenger is sitting above its own belt and
§6 applies verbatim: a win promotes it straight to that belt, a solve is +1,
a failure costs nothing; the defender is at its own belt and so risks −1.
The underdog risks only money, the favourite risks rank.

Which decides the economics. The favourite has no rank upside and real rank
downside, so its only reason to enter is the money: the buy-in is a **purse
the challenger pays for the shot**. A fighter's posted `max_duel_buyin` is
therefore a *floor*, not a ceiling — a price. A challenge at or above
someone's posted price that is declined is on the record; below it, a
decline is silent and free. Grief challenges cannot exist, because the only
weapon a challenger has is a large number and a large number is the thing
the defender wants.

Open: whether to cap the reach (white → blue in one jump is a lottery
ticket, so either +1/+2 tiers or let prices scale with the gap); who picks
the riddle's *class* once its belt is fixed, probably the house, or
collusion reopens; and a per-pair cooldown, because a fighter repeatedly
challenging a friendly senior until one lucky solve is a promotion vending
machine.

**Why anyone would take a sensei seat.** Today, on the numbers, nobody
should: the payout is capped at your own stake, so the best case is
break-even and every other case is a loss. Strictly negative. The 150 × 6
run in docs/model.md measured what the mechanic *does* given participation —
`model.py` enters fighters on a per-archetype probability — not whether a
fighter would choose it. Worth re-running with EV-driven entry before
trusting that senseis fill the low tables for free, and before treating the
NPC retirement as settled.

Two reasons do already exist, unwritten. Bonded winnings are released only
by fighting, so when no table at your belt has quorum the sensei seat is the
only place to bank a fight — worth it whenever the bond held exceeds the
expected cost of the fights that release it. And blue holds: a blue cannot
be promoted, so its own-belt points are pure downside, while a sensei seat
banks a bond fight with its rank untouchable. Both reasons bind only on
senior, bonded, cash-rich fighters, which is the right audience, but both
are situational, so the tables still go dry when nobody is carrying a bond.

Levers, cheapest first: count a sensei fight **double** toward bond release
(costs the house nothing); pay a **teaching fee out of the house's own cut
of the rake**, in rounds that reached quorum only because of the senseis —
the house then pays for its own liquidity, which is what it was paying the
NPCs ~2,000 a round to do, and the invariant that seniors cannot take the
beginners' money survives intact; gate something behind teaching; publish a
teaching record on the board, which does nothing alone but is what the
others need. The sensei *duel* is weaker still — no quorum to solve, so it
is a gift of a capped purse. Treat it as a consequence of the rule rather
than a mechanic anyone will use.

**Title belts as NFTs.** Phase two already lists avatars as Qbay NFTs. The
version worth building instead is an **earned** one: a single asset per
tier, held by the current champion, changing hands only by face-off, with a
slice of the rake paid to whoever holds it. Qubic has no ERC-721 — an asset
issued with one share is the 1-of-1 — and a share transfer is another
feeless transaction confirmed by tick inclusion like every payout. The
settlement documents are already hashed and published, so the asset can
commit to the round that won it.

It answers the three open questions above at once, which is why it is
recorded here and not in phase two. Why enter a duel: a champion who
declines a mandatory challenge **forfeits the belt**, so the title is its
own collateral and the decline problem needs no points and no shame counter.
Why teach: gate title eligibility behind N sensei fights. What happens after
blue: nothing, at present — blue holds, progression stops, and the points
only threaten. Titles are the endgame.

A tournament is then the cheap part. A **gauntlet season** is `spar` with a
leaderboard and one asset transfer at the end; a bracket is a sequence of
duels and costs nothing extra once duels exist. Do the gauntlet first. The
economics invert, because a non-fungible prize has no pot to rake: entry
fees fund the house, the house hands over the asset, and the question is
whether the season's take covers it — which `house metrics` already
answers. Collusion is weaker here than with money, since a syndicate that
sweeps a 1-of-1 wins once rather than repeatedly.

One requirement falls out for the contract, and it is better written down
now than discovered later: **phase one must hold and transfer assets, not
only QU.** In phase zero the house holds the asset and transfers it on
settle, under the usual rule that nothing counts until a node confirms it.
