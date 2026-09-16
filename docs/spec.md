# qdojo phase zero: the specification

Status: draft 0, 2026-09-14. Governs the off-chain phase. The contract phase
gets its own spec once this one has run real rounds.

## 1. Actors

- **House.** One Qubic identity, held by us, that publishes riddles, receives
  stakes, pays winners and publishes settlements. It holds only the pot.
- **Bot.** Any Qubic identity that bows in, commits and reveals. A bot is a
  program its owner runs; the house never runs a player's code.
- **Author.** Whoever writes a riddle. In phase zero the house is the only
  author. An author's identities never play the rounds they authored.
- **Spectator.** Anyone reading the public page. No account, no bot.

## 2. A round

A round is identified by a `round_id` (u32, strictly increasing). Time is
measured in ticks, never in wall clock.

| phase | when | who acts |
|---|---|---|
| lobby | `L+1 .. L+Wl`, where `L` is the tick the LOBBY transaction landed | bots send ENTER with the stake |
| publish | tick `P`, where the PUBLISH transaction landed; sent when at least `min_players` have entered, else the round is void and every entry refunded | house |
| commit window | `P+1 .. P+Wc` | bots send COMMIT with the stake |
| reveal window | `P+Wc+1 .. P+Wc+Wr` | bots send REVEAL |
| settlement | after `P+Wc+Wr` | house evaluates, pays, publishes SETTLE |

`Wc` and `Wr` are in the PUBLISH payload so a bot never has to guess. A tick
is about half a second, so `Wc = 600` is roughly five minutes.

**The lobby.** A round with a lobby announces everything except the riddle
first: fee, minimum players, windows, seed cap and match rate, belt. A
fighter buys a seat with ENTER before knowing the riddle. The first ENTER
per identity inside the window with at least the fee counts; later, late or
underpaid ones are refunded. The house publishes the riddle as soon as the
table has `min_players`, or at the deadline if it has at least that many;
otherwise the round is void and every seat is refunded. In a lobby round a
COMMIT carries no money (any amount is refunded), a commit from an identity
without a seat is a strike, and a seat without a commit forfeits its stake
to the pot (`no_commit`). Rounds without a lobby keep the original flow, the
stake riding on COMMIT. House fighters exist to fill seats, so a table is
never left one short.

## 3. The riddle

A riddle is a JSON document with public fields `round_id`, `title`,
`statement`, `input`, `answer_format` (`integer`, `string` or `hex`). Its
`riddle_hash` is SHA-256 over a domain tag and the canonical JSON of the
public fields, so a bot can verify that the document it fetched is the one
that was published on chain.

The house keeps the answer and a 16-byte `dojo_salt` secret until settlement.
PUBLISH carries `answer_commitment = SHA-256(tag, round_id, dojo_salt,
canonical_answer)`. The salt exists so that a small answer space cannot be
brute-forced from the commitment. At settlement the salt is revealed and
anyone can check that the winning answer hashes to the published commitment.
That is how spectators verify the house did not move the goalposts.

Answers are canonicalised before hashing (`hashing.canonical_answer`):
integers to their decimal string, strings to NFC with surrounding whitespace
stripped, hex lower-cased without a `0x` prefix.

## 4. Commit and reveal

A bot never sends its answer in the clear during the commit window.

- COMMIT carries `SHA-256(tag, round_id, identity, salt, canonical_answer)`
  and the stake as the transaction amount. Binding the identity into the
  commitment means one bot cannot copy another's commitment.
- REVEAL carries the salt and the answer. It is valid only if it reproduces
  the identity's own commitment and the answer matches the house commitment.

The first COMMIT per identity inside the window counts. Later commits from the
same identity are ignored and recorded as a strike. The first valid REVEAL per
identity counts.

## 5. Money

- **Stake.** In a lobby round the ENTER amount; without a lobby the COMMIT
  amount. It must be at least the round's `entry_fee`.
- **Seed.** PUBLISH announces a `seed_cap` and a `match_bps`. The house adds
  `min(seed_cap, counted stakes × match_bps / 10000)` to the pot, plus any
  carry from earlier rounds. With `match_bps = 10000` the house matches the
  fighters one to one: an empty round costs nothing, and one fighter alone
  can never take out more than a multiple of what they put in. With
  `match_bps = 0` the seed is fixed at `seed_cap` (the round-one behaviour).
  Stakes of the house's own fighters join the pot but are never matched:
  the house does not match its own money, so a table with only house
  fighters at it adds no seed and simply carries.
- **Pot** = seed actually added + carry in + every counted stake.
- **Rake** = `rake_bps / 10000` of the counted stakes, never of the seed. It
  is split three ways by the round's `rake_house_bps`, `rake_dev_bps` and
  `rake_share_bps`: the house treasury keeps its share, the dev/team share
  is paid out with the settlement, and the shareholder share accrues to a
  pool paid to the house asset's holders. The winners' side of the pot is
  `pot - rake` however the rake is split.
- **Solvers** are every identity with a counted commit and a correct reveal.
- **Payout mode** is set per round in PUBLISH:
  - `first` (default): the solver with the earliest commit tick takes
    `pot - rake`. Solvers that share that tick split it equally. Later
    solvers are recorded as `solved`, get nothing, and keep their stake in
    the pot. A commit needs the answer, so on a riddle that takes an agent
    real time, first is skill, not network latency.
  - `split`: every solver shares `pot - rake` equally.
  - `podium`: the first three correct commits take 5:3:2 of `pot - rake`
    (5:3 for two, all for one); same-tick solvers are ordered by
    transaction id. Later solvers are `solved`, unpaid.
  The integer remainder carries into the next round's seed.
- **Bond.** PUBLISH announces `bond_bps` and `bond_rounds`. That share of
  every win stays with the house as the winner's bond and is paid out with
  the settlement of the round in which the winner completes `bond_rounds`
  further fights. A holder who has not done so within 20 rounds forfeits the
  bond to the pot. Bonds are listed in `bonds.json`; every hold, release and
  forfeit is in the hashed settlement.
- **No winners:** `pot - rake` carries into the next round. The house keeps
  only the rake.
- **Refunds.** A commit that was underpaid or landed outside the window is
  refunded in full at settlement. A stake behind a wrong or missing reveal
  stays in the pot: you paid to play.

Every payout is a plain transfer from the house identity, confirmed by tick
inclusion and then by re-reading the house balance. Settlement is idempotent:
a payout recorded as confirmed is never sent again.

## 6. Belts

Every identity carries a belt: white, yellow, orange, green, blue. Everyone
starts white. Each round's riddle has a belt. **You may sit at a table at
your belt or above, never below**: an ENTER or COMMIT from an identity
ranked above the riddle is refused (`outranked`) and refunded. A bot tuned
for one kind of riddle is therefore promoted away from it and has to hold
its own across the whole range, or be demoted back.

**The sensei seat.** A round may open its low tables to fighters from above
(`sensei` in LOBBY and PUBLISH). A fighter sitting below its own belt is a
*sensei*: it pays the entry fee and its stake joins the pot like anyone's,
but it can **win back at most its own stake** — any surplus it would have
won goes to the winners who belong at that belt, or carries — and the round
**moves no belt points for it**, up or down. It still counts as one of the
fights that release its bond. So a senior fighter has a reason to keep the
beginners' tables alive without being able to take the beginners' money.
Without sensei seats, a fighter who sits below its belt is refused
(`outranked`) and refunded.

Points move at your own belt: winner +2, solved +1, any failure -1. At +3
you are promoted one belt and points reset; at -3 you are demoted one belt
and points reset; white cannot fall further, blue holds. Above your belt a
win promotes you straight to that belt, a solve is +1, a failure costs
nothing. The house records the belt state before each settlement and every
change inside the hashed settlement document, and publishes the whole
ladder in `belts.json`, so anyone can replay it.

## 7. Manners

The dojo has etiquette, and etiquette is enforced.

- A bot **bows** once before its first round: a BOW transaction carrying a
  display name. Unbowed identities can still play; they are listed as
  "unnamed" on the page. Later phases will require the bow.
- **Strikes** are recorded for duplicate commits, malformed payloads, reveals
  without a commit, and more than 8 dojo transactions in one round. Phase
  zero records strikes and publishes them. Phase one evicts on them.
- **The API** (docs/api.md) is the whole developer surface: published
  riddles with answers, settlements, fighter performance, the ladder. No
  riddle generator and no offline harness are provided; you train on what
  the dojo has already fought.

## 8. What is published

For every round the house publishes, on chain and on the page:

- the PUBLISH transaction (riddle hash, answer commitment, windows, fee, URI)
- the riddle document at the URI
- the settlement document: every observed transaction with its verdict,
  the winners, every payout with its transaction id and confirmed tick,
  `dojo_salt`, the carry into the next round
- the SETTLE transaction carrying the settlement document's hash

## 9. Verification rules the house obeys

- Discovery of transactions goes through the indexer, and only up to the
  tick the indexer itself reports as processed, minus a margin. An empty
  answer for ticks past that point is not "no entries", it is "not indexed
  yet" (learned in round 1, 2026-09-15). The collector also re-reads a window
  behind its pointer every pass.
- Every transaction of every counted entry is then confirmed in its tick
  against a node before settlement may plan a single payout. A node that
  cannot answer aborts; a node that disagrees with the indexer aborts.
- The house never trusts a send. It confirms inclusion, then re-reads its own
  balance and compares to the expected delta.
- Balances are read at the moment they are needed and never stored as facts.
- An indexer or node failure aborts settlement. It is never read as "no
  entries".

## 10. Not in phase zero

Spectator betting, NFTs and avatars, seats and auctions, NPC bots, community
riddles, oracle-fed riddles, the smart contract. Each has a line in
`docs/roadmap.md`.
