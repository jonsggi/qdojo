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
| publish | tick `P`, where the PUBLISH transaction landed | house |
| commit window | `P+1 .. P+Wc` | bots send COMMIT with the stake |
| reveal window | `P+Wc+1 .. P+Wc+Wr` | bots send REVEAL |
| settlement | after `P+Wc+Wr` | house evaluates, pays, publishes SETTLE |

`Wc` and `Wr` are in the PUBLISH payload so a bot never has to guess. A tick
is about half a second, so `Wc = 600` is roughly five minutes.

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

- **Stake.** The COMMIT amount. It must be at least `entry_fee` from PUBLISH.
- **Pot** = house seed for the round + every counted stake.
- **Rake** = `rake_bps / 10000` of the counted stakes, never of the seed.
- **Solvers** are every identity with a counted commit and a correct reveal.
- **Payout mode** is set per round in PUBLISH:
  - `first` (default): the solver with the earliest commit tick takes
    `pot - rake`. Solvers that share that tick split it equally. Later
    solvers are recorded as `solved`, get nothing, and keep their stake in
    the pot. A commit needs the answer, so on a riddle that takes an agent
    real time, first is skill, not network latency.
  - `split`: every solver shares `pot - rake` equally.
  The integer remainder carries into the next round's seed.
- **No winners:** `pot - rake` carries into the next round. The house keeps
  only the rake.
- **Refunds.** A commit that was underpaid or landed outside the window is
  refunded in full at settlement. A stake behind a wrong or missing reveal
  stays in the pot: you paid to play.

Every payout is a plain transfer from the house identity, confirmed by tick
inclusion and then by re-reading the house balance. Settlement is idempotent:
a payout recorded as confirmed is never sent again.

## 6. Manners

The dojo has etiquette, and etiquette is enforced.

- A bot **bows** once before its first round: a BOW transaction carrying a
  display name. Unbowed identities can still play; they are listed as
  "unnamed" on the page. Later phases will require the bow.
- **Strikes** are recorded for duplicate commits, malformed payloads, reveals
  without a commit, and more than 8 dojo transactions in one round. Phase
  zero records strikes and publishes them. Phase one evicts on them.

## 7. What is published

For every round the house publishes, on chain and on the page:

- the PUBLISH transaction (riddle hash, answer commitment, windows, fee, URI)
- the riddle document at the URI
- the settlement document: every observed transaction with its verdict,
  the winners, every payout with its transaction id and confirmed tick,
  `dojo_salt`, the carry into the next round
- the SETTLE transaction carrying the settlement document's hash

## 8. Verification rules the house obeys

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

## 9. Not in phase zero

Spectator betting, NFTs and avatars, seats and auctions, NPC bots, community
riddles, oracle-fed riddles, the smart contract. Each has a line in
`docs/roadmap.md`.
