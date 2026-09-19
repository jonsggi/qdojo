# Roadmap

**The contract comes last.** Not because it is hard, and not because the
GQMPROP is a problem — it is not. Because every rule we change before the
contract is free, and every rule we change after it costs a governance
round-trip. The off-chain house is the cheapest place in this project to be
wrong, so implement and check the complete game there before porting its rules
to the contract. Engineering tests and simulations inform that work; they do
not establish external demand or sustainable economics.

**Release decision, 2026-09-19:** finish the full intended product before
onboarding the ten external fighter owners. Duels, cups, seasons, trophy NFTs
and community challenges belong in that product. There is no intermediate
external pilot gate. The contract remains last in implementation order; the
working interpretation includes it before onboarding, with deployment scope
still to be confirmed explicitly.

The current agreed rules and remaining specification questions are recorded in
[Launch product decisions](product-decisions.md). They supersede the historical
sketches below wherever they address the same mechanic.

**Verification decision, 2026-09-19:** use challenges settled through hash
commitments for now. Defer open-ended quality scoring, oracle/EVM judging,
custom verifier runtimes and execution proofs. Hash-based partial-credit
formats remain proposals. Preserve [EVM oracle research](verification-research.md)
as a deferred option; its integration, cost, latency and trust boundaries have
not been validated end to end.

**Content direction:** prioritise an extensive, frequently extended
[riddle catalogue](riddle-catalogue.md). New families, explicit rule variants
and combined tasks should reward improvements to fighter scripts and procedures.
The catalogue records 16 current kinds and 40 candidates; it is a design backlog,
not a claim that the new generators exist. Content releases should preserve a
stable solver interface and hash-based settlement.

---

## Phase zero, off chain — COMPLETE (2026-09-16)

The whole game run by a house process: it evaluates and pays, and every round
is published and verifiable. 118 settled rounds on chain across an 18-fighter
cohort.

- [x] spec, wire protocol, lore, developer API (docs/api.md), modelling notes (docs/model.md)
- [x] pure core: hashing, payloads, round evaluation, settlement
- [x] chain layer: fake for tests, qubic-cli + indexer for real, indexer-lag safe
- [x] pure-Python signing, so a bot needs no qubic-cli: K12, FourQ, SchnorrQ,
      identities, transactions and the node protocol in `qdojo.qubic`, the
      default chain since 2026-09-19, checked byte-for-byte against the
      reference by `scripts/crosscheck-signer.py`
- [x] house CLI: lobby / publish / collect / settle / void / export / metrics / model / distribute-shareholders
- [x] bot CLI: init, bow, run with any solver, stats, shares, dividend, strategy hook
- [x] spectator page: lobby table, rounds, results, void, fighter profiles, halls of fame, hash verify
- [x] first live round (2026-09-15) and two full sparring runs (118 rounds)
- [x] economics: stake-matched adaptive seed, lobby quorum, belts, bonds, podium, three-way rake
- [x] mathematical model calibrated against the live cohort; gate + rake + NPC findings (docs/model.md)
- [x] self-evolving tool-making fighters, LLM fighters on cheap models, house-funded NPCs

## Phase one, approachable — COMPLETE (2026-09-17)

Phase zero proved the game works. It did not make it possible for anybody else
to play. This phase was the difference between a thing that runs and a thing a
stranger can join.

- [x] decoded tick pages: every tick on the site links to our own page, which
      says in English who did what, for how much, with the raw payload behind a
      toggle. 131 legacy frames that no longer decode are resolved from the
      house's own records rather than guessed at.
- [x] in-game help on every metric, and a rules screen that teaches the whole
      game with the lore beside the mechanic it explains
- [x] `llms.txt`, written for a coding agent, and signed on chain
- [x] **a training fight**: `qdojo train` runs your solver against settled
      rounds and reports where you would have placed and what the purse would
      have been. No seed, no QU, no node, no signer. This is the front door.
- [x] one command: `git clone … && cd qdojo && ./dojo`
- [x] a solver chooser — bare bones, prompt-driven, bring your own — asked
      before any provider question, so the free path never mentions an API key
- [x] prompts as editable `.md` files; a save is live on the next round
- [x] `qdojo bot dash`: a private page on 127.0.0.1 with your stats, your
      training scorecard and your prompt files, editable in the browser
- [x] the spectator page deployed off the tailnet, served from a container
- [x] a private repository, and a test that every command we publish parses

Left open, small: a real hostname and TLS for the deployment (needs a DNS
record on `jonsggi.com`); the site's data is a committed snapshot, so a live
house needs a push story; `riddles.py` is house-internal and must move out of
the public package before the repo opens.

## Phase two, the game deepens — NEXT

The rules are cheap to change right now. Build the full scope below before
external onboarding, using [the agreed product rules](product-decisions.md).
Open parameters and implementation details remain to be resolved; these
features are not marked implemented merely because their direction is agreed.

- **fighter avatar NFTs as paid registration**: a persistent competitive
  identity whose belt, record and outstanding bonds survive a sale or wallet
  change; one seat per fighter per round. Training stays free. See
  `docs/spec.md` §11 and the implementation sequence below.
- ten gifted founding fighters with distinctive appearances and ordinary
  competitive rights; low initial ordinary-fighter prices and further batches
  as the community grows
- meaningful challenge families with canonical answers settled through hashes,
  free training and actionable explanations of losses; debugging can be part
  of solving, but arbitrary patch verification and open-ended quality scoring
  are deferred; partial-credit scoring through hashes remains to be specified
- a versioned catalogue and authoring/release workflow for frequent family,
  rule-variant and composition additions, with reference answers, practice
  specimens, difficulty checks and explicit generation/settlement cost bounds
- always-open regular lobbies that wait for quorum, autonomous participation
  limits, and modest fixed seeds within a finite subsidy budget
- four-epoch seasons: every regular round counts toward one overall champion;
  3/2/1/0 scoring also rewards senseis at lower tables; lifetime records persist
- a freely transferable season champion trophy NFT, with no automatic cash
  reward or rake rights; archived championship results remain with the winner
- standalone duels in single-round, best-of-three and best-of-five formats,
  full purse less rake regardless of belt, with no league or belt points
- scheduled knockout cups and championship playoffs: best-of-three early
  matches and best-of-five finals; cup winner takes the entire prize pool
- reviewed community generators and verifiers, random selection after entries
  lock, no author deposit, and authors paid 10% of the house's rake portion on
  regular rounds using their families
- extend the finite belt ladder through brown to black, with meaningfully
  harder challenges across families; every new fighter starts at white and
  earns promotion at its own belt, with no upward regular-table entry or rank
  jumps; seniors may still enter lower tables as senseis; seasons and cups
  provide continuing competition without resetting career rank

### Fighter registration: implementation sequence

1. **Validate purchase and farming economics.** Model repeated fresh fighters
   and coordinated operators: shared solvers, podium capture, deliberate
   demotion, subsidies and resale. Acquisition price is not all sunk cost if
   the fighter can be resold. Compare prices and issuance policies against
   farming returns, including the low-price launch policy and gifted fighters.
   Record registration revenue separately from recurring rake revenue.
   Newcomer willingness to buy remains an observation for after launch.
2. **Specify the persistent career.** Key rank, history, strikes, teaching
   credit and bonds by fighter asset ID. Define owner/operator authorization,
   ownership handover for open rounds, fixed round payout recipients, bond
   handover and migration of existing fighters. Include house-funded and
   gifted fighters. Transfer cannot reset progression, duplicate a seat or
   renew a bond's expiry.
3. **Build and validate off-chain registration.** Verify confirmed ownership,
   update messages and commitments to identify the fighter, enforce one seat
   per fighter per round, and publish ownership and career history. Resolve
   the existing financial/public-operation audit gates and NFT release
   findings (AUD-009–010) before activation or sale. Validate transfer,
   delegation, duplicate-entry and recovery behavior.
4. **Integrate registration with the complete game.** Exercise ownership and
   handover across regular rounds, seasons, duels, cups and trophy issuance.
   Keep training available without a wallet or purchase. Set explicit launch
   prices, batch policy and subsidy limits; tests and simulations precede
   onboarding, while real conversion and retention evidence follows launch.

The economics to settle here, because they are the contract's parameters: the
seed taper, rake split, bond, fighter acquisition cost and supply, and whether
rounds sustain the house without subsidy or continuing NFT sales. Include
contract execution/state costs, oracle queries and retries, and any EVM/proof/
relay costs against the house's retained rake after all allocations. The
dated execution-cost brief in `docs/model.md` is part of the architecture
decision; existing off-chain margin estimates omit these expenses.
`house model` and `house metrics`
are the starting tools; acquisition, resale and
coordinated-fighter strategies need to be added. Correct the model's sensei
cap to run before bonds, matching settlement, and model entry decisions from
expected returns and costs before treating full simulated tables as evidence
of voluntary participation.

## Phase three, the contract — LAST

Move the settled rules into a smart contract. Everything in this list is
blocked on phase two being *decided*, not merely attempted.

- seats, auctions, inactivity eviction, NPC seats acting at tick boundaries
- commit and reveal inside the contract, pot and rake in state
- on-contract bond custody and shareholder claims
- the sensei seat and the chosen gate; four-epoch league standings separate
  from persistent belt progression
- fighter NFT ownership and operator authorization, persistent career and
  bond state keyed by asset ID, one seat per fighter per round, and safe
  ownership handover across pending rounds and payouts
- **assets, not only QU** — ownership checks for registered fighters and
  whatever custody or transfer mechanism the specified rules require,
  including season champion trophy issuance and ownership
- duels, cup brackets, match series, bounded draws/replays, prize accounting,
  challenge selection and author payments under the agreed product rules
- IPO of 676 shares, fees to shareholders
- proposal through GQMPROP

## Later, unscheduled

- any marketplace integration for fighter resale; basic ownership and
  transfer rules belong in phase two, independent of a marketplace
- parimutuel spectator pools (Quottery's model), after legal review
- external-data riddles; EVM-oracle settlement is a separate architecture
  candidate described in [verification research](verification-research.md)

## After the complete release: onboard the first ten

Gift the distinctive founding fighters to independent builders recruited
through Qubic Discord. They use the finished product; this is not an earlier
phase-two pilot. Observe solver improvements, return after losses, waiting
times, purchased registrations beyond the gifted cohort, recurring costs and
coordinated-fighter behaviour to inform subsequent releases. Gifted entry does
not itself demonstrate willingness to buy a fighter.

---

## Sketch: the riddle seed from the chain (2026-09-18, Joel)

**The idea.** `riddles.py` is a deterministic generator: `generate(belt, rng,
round_id)`. Today the house seeds it with OS entropy (`random.Random(None)`),
so the seed exists only in the house's memory and is never published. Joel's
proposal is to take the seed **from the Qubic chain instead** — a future tick's
data — which removes the house's ability to grind for a riddle it likes, and
makes the choice publicly recomputable after the fact.

It is the right instinct and it fixes a real asymmetry. **It also has a catch
that decides how it must be built.**

**The catch: a public seed plus a public generator is a public answer.** Every
generator in `riddles.py` computes its own canonical answer. If both the seed
and the generator are public, then the instant the seed tick lands, anyone
running the generator has the answer. The race stops being "who can solve it"
and becomes "who can run a script fastest", which is worse than what we have.

So exactly one of these has to hold:

1. **Hard riddles.** The seed is public, the generator is public, and the
   riddle's answer is not computable by re-running the generator — the
   "code that is broken and must be fixed" class the lore promises. This is
   the trustless endgame and the reason to build that riddle class first.
2. **Private generator, public seed.** The house cannot choose the riddle but
   still knows the answer early. Strictly better than today; the existing
   answer commitment already covers the house changing its mind.
3. **Pre-committed set.** The house publishes hashes of N riddles in advance
   and the chain seed selects which one. The house cannot grind, and it knows
   the answers — same trust level as (2) with less machinery to keep secret.

**Design note for whichever path.** The seed tick must be in the FUTURE at the
moment the house commits to using it, and the commitment must name the tick.
Otherwise the house reads the tick first and only then decides to use it, which
is grinding by another name. `SETTLE` already publishes an evidence document;
naming the seed tick in `LOBBY` or `PUBLISH` is the natural place.

Not decided, not costed. It belongs with phase two, because it is cheap to
change now and a governance round-trip later.

## Historical sketches — superseded where decided (2026-09-17)

**Historical reasoning only.** The 2026-09-18–19 discussion settled several
of these questions differently. Use [Launch product decisions](product-decisions.md)
for current intended behaviour: in particular, duels have full-purse payouts
without belt progression, unresolved duels refund without rake, championships
use four-epoch seasons and freely transferable trophies, and community authors
need no deposit. The proposals below are retained as context, not as a second
active ruleset or an implementation sequence.

Updated 2026-09-18 with fighter registration as the agreed direction.
Duels, sensei incentives
and titles are related proposals; none of their prices or rewards is settled.

**Buy a fighter, keep its career.** A fighter avatar NFT is the credential
for paid competition, with a stable identity that carries its belt, record,
strikes, teaching credit and outstanding bonds through every ownership change.
The solver can change; the career persists. One fighter gets one seat per
round. Training and spectating require no NFT.

This puts a price on restarting at white belt. It raises the cost of farming
but does not establish one owner per fighter: an operator can buy several,
share a solver and coordinate entries. Model that operator's total returns,
including resale, rather than assuming the whole purchase price disappears.
Also test whether progression makes a fighter more desirable to buyers;
that could reward developing fighters, but resale value is not promised.
Issuance, pricing, transfer mechanics and treatment of existing fighters are
open decisions listed in `docs/spec.md` §11.

The fighter is distinct from a championship title. Owning a competitor is
the entry requirement; becoming champion requires a competitive result.

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

The duel carries the **defender's** belt. When that is above the challenger's
belt, §6 gives the challenger immediate promotion on a win, +1 on a solve,
and no point loss on failure. At equal belts both use the ordinary rules.
The defender earns +2 for winning or +1 for a correct slower answer, and
loses a point on failure. Below blue it can still be promoted; at blue it
can rebuild points against demotion even though it cannot climb further.

The buy-in gives the defender a money incentive, but both sides escrow, so
a larger offer also requires more capital and puts more at risk. A posted
minimum acceptable buy-in should be named as a minimum, with a separate
maximum stake the defender is willing to risk. Optional duels may be declined
without penalty. A large offer does not prevent griefing through timing,
volume or unaffordable stakes; qualified title challenges need bounded stakes,
a queue or cooldown, and scheduled defense windows before forfeiture can be
fair. Paid fighter registration raises the cost of rotating challengers but
does not eliminate that strategy.

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

**Title belts, separate from fighter NFTs.** First test an earned champion
record in a gauntlet season. A later trophy could be a single asset per tier
associated with the winning fighter and the round that won it. Its ownership,
competitive champion status and any share of the rake are separate rights
that need explicit rules. A trophy sale alone does not award a championship.
Decide what happens when the champion fighter is sold, promoted or inactive,
and how custody permits a title to be forfeited or reassigned, before issuing
title assets or promising revenue to their holders.

Titles could connect three incentives: qualified defenses give champions a
reason to accept duels, a teaching requirement could make sensei fights worth
taking, and championships give blue fighters an endgame. These are hypotheses
to test. Define challenger qualification, bounded defense obligations and
inactivity handling before making a declined challenge cost a title. If
teaching gates eligibility, define a qualifying contribution and test whether
coordinated fighters can manufacture it.

A tournament is then the cheap part. A **gauntlet season** is `spar` with a
leaderboard and one asset transfer at the end; a bracket is a sequence of
duels and costs nothing extra once duels exist. Do the gauntlet first. The
economics invert, because a non-fungible prize has no pot to rake: entry
fees fund the house, the house hands over the asset, and the question is
whether the season's take covers it — which `house metrics` already
answers once season costs and rewards are recorded. A scarce prize does not
remove collusion incentives, especially if it also pays continuing revenue;
model coordinated entrants here too.

One requirement falls out for the contract, and it is better written down
now than discovered later: **phase three must understand fighter assets and
ownership, not only QU.** Title custody and transfer requirements follow from
the rules tested off chain. Any transfer counts only after confirmed chain
inclusion.
