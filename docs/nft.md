# Fighter NFTs

> **Purpose:** what a fighter NFT is, what owning one does in the game, how it is traded, how the simulation models Qubic, and what a real Qubic backend still needs. \
> **Audience:** the owner (decisions marked **Proposal**), contract and backend implementers, reviewers of AUD-009 and AUD-010. \
> **Status:** normative for the simulated arena (`combat/nft.py`, `combat/live.py`); the Qubic backend (`combat/nft_qubic.py`) is a stub that never sends. Proposals in §2 and §3 stand until the owner accepts or changes them. \
> **Last reviewed:** 2026-09-27

Nothing here mints, sells or moves a real asset. The simulated chain uses fake
QU and synthetic identities. The rules below are what the simulation enforces
today and what the real backend must enforce.

## Contents

- [1. The model](#1-the-model)
- [2. Game rules](#2-game-rules)
- [3. Market and economics](#3-market-and-economics)
- [4. The simulated market](#4-the-simulated-market)
- [5. Backends and the Qubic facts they rest on](#5-backends-and-the-qubic-facts-they-rest-on)
- [6. Public data](#6-public-data)
- [7. Frozen art and metadata](#7-frozen-art-and-metadata)
- [8. Journal, replay and restarts](#8-journal-replay-and-restarts)
- [9. Decisions for the owner](#9-decisions-for-the-owner)

## 1. The model

One fighter is one token. A token is a Qubic **asset** with exactly **one
share**. Qubic identifies an asset by its issuer's identity and its name (§5.1).

| Field | Value in the simulation |
|---|---|
| issuer | the collection's issuer identity (`identity("qdojo-sim-issuer")`) |
| name | `QF` plus the serial in base 36, 7 characters: `QF00001`, `QF00002`, … (up to 36⁵ − 1 tokens) |
| shares | 1, never divisible (`numberOfDecimalPlaces` 0) |
| owner | who owns the share. **The game reads the owner** |
| possessor | who holds the share. It equals the owner unless the owner hands it to a custodian |
| manager | the contract that may move the share: `QDOJO` (default) or `QX` |
| creator | receives the royalty (§3): the house for house fighters, the builder for an outside fighter |
| founding | set at mint for the deployment's founding fighters |
| fighter_id | the game's 32-byte fighter ID. The token records it; the contract maps it to the asset |

The port is `FighterNFTs` (`combat/nft.py`). Every caller uses it: the arena,
the join service, the exporter and the tests. Writes return a `Receipt` to
poll, never a result, because a real write is a transaction.

| Operation | Who | Effect |
|---|---|---|
| `issue` | issuer | Mint the token to its first owner, with its creator and founding flag |
| `transfer` | owner and possessor | Give the token away (transfer fee, §3) |
| `ask` / `cancel_ask` | owner and possessor | List at a price, re-price, or withdraw. One ask per token |
| `bid` / `cancel_bid` | anyone but the owner | Offer a price. The full price is attached and held in escrow. One bid per bidder per token |
| `settle` | anyone | Execute a crossed book once the fighter is idle. The contract's END_TICK normally does this |
| `custody` / `release` | owner, then custodian | Hand possession to a custodian and get it back. Ownership does not move |
| `manage` | owner | Move management rights between QDOJO and QX (§5.3) |
| `token`, `owner`, `possessor`, `collection`, `tokens_of`, `book`, `history`, `sales` | anyone | Confirmed state as public JSON |

A rejected operation changes nothing and returns a code: `UNKNOWN_TOKEN`,
`BAD_NAME`, `DUPLICATE`, `NOT_ISSUER`, `NOT_OWNER`, `NOT_POSSESSOR`,
`LOCKED`, `RESERVED`, `INSUFFICIENT_FUNDS`, `BAD_PRICE`, `NO_ORDER`,
`NOT_MANAGED`, `SELF_TRADE`, `BOOK_FULL` or `BAD_ARGS`.

## 2. Game rules

These rules resolve AUD-010's open questions. Each one is a **Proposal** until
the owner accepts it; the simulation already enforces them.

**R1 Minting (Proposal).** A token is minted when its fighter is registered:
- a house fighter by the house, to its demo owner, with the house as creator;
- a founding fighter the same way, marked `founding`;
- an outside builder's fighter to the builder, who is also its creator
  (`join.py`).
The contract recognises the asset (AdminRegisterAsset) in the same step. There
is no free-standing mint of art without a fighter.

**R2 The token is the fighter (Proposal).**
- Owning the token owns the fighter. The owner registers it
  (RegisterFighter), chooses its operator (SetOperator) and so its bot, and
  enters it in ranked play, duels and cups.
- A transfer changes the owner and nothing else. The new owner must register
  the fighter. The contract then sets owner = operator = the new owner and
  increments `auth_version`, so the old operator's signatures stop counting.
- The fighter keeps its rating, record, faults, history, season standing,
  **belts and titles**. Titles belong to the fighter and cannot be transferred
  on their own (the belts-and-titles track owns their rules;
  [competition.md](competition.md)).
- The token carries no key, seed or wallet. Selling it never hands over the
  seller's wallet or money.

**R3 Rewards go to the owner (Proposal).** Winnings are credited to the
`payout_recipient` that each admission snapshots: the owner at entry time. An
owner who wants the operator paid pays the operator privately. Reasons:
- the operator can change mid-season;
- the owner is the one party the chain can always identify (the asset owner);
- the contract already works this way (protocol.md §1, participant record).

**R4 Transfers happen only between contests (Proposal).** A QDOJO-managed
token changes hands only while its fighter is **IDLE**: not queued, not
offering or accepting a duel, not in a contest, not registered in a cup.
- A gift transfer of a busy fighter is refused (`LOCKED`).
- Listing and bidding stay open while it fights.
- A bid that meets the ask while the fighter is busy is **agreed, not
  executed**. The book is marked crossed and the sale executes at the first
  END_TICK the fighter is idle, at the price fixed when it crossed. Either side
  may cancel before that.
- Open offers are not cancelled for the buyer. A fighter is idle when it sells,
  so it has none; stale duel challenges to it fail on `auth_version`.
- For a share moved to QX (§5.3), QX cannot see contests. The contract's
  ownership snapshots still send every payout to the owner who entered it, and
  the new owner simply registers afterwards.

**R5 Custody (Proposal).** The owner may hand possession to a custodian (a
lending desk, an escrow contract). Ownership and every game right stay with
the owner, including winnings. While possession is away, the owner cannot
list, bid on or transfer the token. Only the custodian can return it.

**R6 Metadata is static (Proposal, AUD-009).** Art, traits and bio are frozen
at release (§7). Rank, belts, titles and record are live game data. They
appear on the site and in the API, never in token metadata.

**R7 Rights (open).** The licence for the artwork and any commercial or
display rights need the owner's decision and a legal review (AUD-010). Until
then the site says only that a token is the fighter and nothing more.

## 3. Market and economics

The QDOJO market is an order book modelled on QX (§5.1), with two additions
QX lacks: the contest lock (R4) and a creator royalty.

- **Orders.** An ask **reserves** the share, as QX does: a reserved share
  cannot be transferred until the ask is cancelled (`RESERVED`). A bid attaches
  its full price, which the market holds in escrow until it trades or is
  cancelled. A bidder's new bid replaces its old one and refunds it. A book
  holds at most 16 bids.
- **Matching.** Price, then time. An incoming order trades at the **resting
  order's price**, as on QX: an ask below the best bid sells at the bid; a
  bid above the ask pays the ask, and the excess is refunded. A crossed book
  settled later trades at the older order's price.
- **Fees, per sale of price P, taken from the seller** (Proposal):
  - market fee: 250 bps of P, to the house;
  - creator royalty: 250 bps of P, to the token's creator, unless the creator
    is the seller;
  - the seller receives P − fee − royalty.
- **Gift transfer** (Proposal): 100 QU to the house. That is QX's transfer fee.
- **Recording.** The policy (`NFTPolicy`) is written into the collection's
  genesis record, so a replay never picks up changed defaults.

QX itself charges 0.3% per trade (§5.1) and pays it to its shareholders. On
QX there is no royalty and no lock.

## 4. The simulated market

`live.Market` drives the demo. Every `market_every` ticks, the arena's own
identities act through ordinary NFT transactions on the simulated chain, with
latency, reordering and drops.

- **Owners** of non-founding house fighters (demo owners and collectors) may:
  - list at 1.05–1.5× the fighter's value;
  - cut an unsold ask by 5% (never below 0.85× value);
  - take a standing bid of at least 0.95× value by asking at its price.
- **Collectors** bid 0.8–1.15× value on the listing that looks cheapest.
  Sometimes they lowball an unlisted fighter at 0.6–0.9×. They withdraw a bid
  after three steps. A collector is created when needed, up to 12, and keeps
  what it buys and may list it again.
- **Settlement.** A sale settles in the market, or at the first idle END_TICK
  (R4). The new owner registers the fighter and a new bot runs it.
- **Value** is public and deliberately simple: rating, record and experience
  (`Market.value`). The market shows prices, not real demand.
- **Outside builders' fighters** are never traded on the builder's behalf.

## 5. Backends and the Qubic facts they rest on

`nft_backend: sim | qubic` is chosen when an arena is created
(`qdojo combat live --nft-backend`), stored in its `chain.json`, and published
in the export's deployment block. Only `sim` runs.

### 5.1 Qubic facts used

Checked on 2026-09-27 against the primary sources where stated. **Uncertain**
marks what was not verified against source.

| Fact | Source |
|---|---|
| An asset is (issuer identity, name). The name has 1–7 characters: an upper-case letter first, then A–Z or 0–9. It is stored as a zero-padded uint64 | qubic/core `doc/contracts.md`; `qdojo.qubic.contracts.asset_name_bytes` |
| Shares have separate **ownership** and **possession** records, and each record names its **managing contract**. Only the manager moves them. Management moves with `TransferShareManagementRights` (release/acquire callbacks) | `doc/contracts.md`; `Qx.h` `PRE_RELEASE_SHARES`/`PRE_ACQUIRE_SHARES` (the callback details are **uncertain**, from a summary) |
| QX is contract index 1; QBAY, the NFT marketplace contract, is 12 | `src/contract_core/contract_def.h` |
| QX procedures: IssueAsset 1, TransferShareOwnershipAndPossession 2, AddToAskOrder 5, AddToBidOrder 6, RemoveFromAskOrder 7, RemoveFromBidOrder 8, TransferShareManagementRights 9. Functions: Fees 1, AssetAskOrders 2, AssetBidOrders 3, EntityAskOrders 4, EntityBidOrders 5 | `src/contracts/Qx.h` (REGISTER_USER_*) |
| QX fees: issuance 1,000,000,000 QU; transfer 100 QU; trade 3,000,000 per 10⁹ (0.3%, `price·shares·fee/10⁹ + 1`, from the seller). They are paid to QX's shareholders at END_TICK, not burned | `Qx.h` INITIALIZE, END_TICK (values since epoch 138; read `Fees` live) |
| An ask **reserves** possessed shares and escrows nothing. A bid must attach `price × shares`, and the excess is refunded. An incoming order trades at the resting order's price. Orders are removed by (price, shares) | `Qx.h` AddToAskOrder / AddToBidOrder / RemoveFrom* |
| Input layouts: order input `{issuer id, assetName u64, price s64, shares s64}` is 56 bytes; transfer input is 80 bytes; IssueAsset input is 32 bytes with 7 padding bytes; management input `{Asset, shares s64, newIndex u32}`, which we pad to 56 (**padding uncertain**) | `Qx.h` structs; `qdojo.qubic.contracts` (checked against qubic-cli) |
| A contract call is a transaction to the contract's key (its index in the first 8 bytes, then zeros), with `inputType` = procedure, amount = attached QU, and the input struct. It targets a tick; if it is not included in that tick it is dropped and must be resent | `doc/contracts.md`; `qdojo.qubic.tx`; docs.qubic.org/developers/transactions (targeting ~+10 ticks is community practice, **uncertain**) |
| Inclusion does not mean success. A procedure's outcome shows only in its effect (owner, orders, balances) | `Qx.h` (procedures return outputs, no receipts); no status endpoint found |
| RPC: `/v1/tick-info`, `/v1/broadcast-transaction`, `/v1/querySmartContract`, `/v1/assets/{id}/owned\|possessed\|issued`. Testnet: `https://testnet-rpc.qubic.org` | docs.qubic.org/api/rpc, qubic-http README, docs.qubic.org/developers/testnet-resources (endpoints **not exercised live**) |
| QBAY keeps NFTs as its own records, **not Qubic assets**: creator, possessor (no separate owner, no managing contract), a 0–100% royalty and a ≤ 59-byte URI. It charges 2% to the market and 1% to shareholders per sale; royalty is paid on QBAY sales only | `src/contracts/Qbay.h` at e3ef766; [the ecosystem research](research/qubic-nft-ecosystem-2026-09-30.md) §1.1 |
| A 1-share QX asset used as an NFT is plausible but **not found documented** as a convention | — |

### 5.2 The simulated backend

`SimFighterNFTs` over `AssetLedger` models the following:
- the asset layer: issuer, names, one share, owner, possessor, manager;
- the QDOJO market: reserved asks, escrowed bids, maker-price matching, fees,
  royalty, the lock, deferred settlement at END_TICK, custody;
- a QX-managed share that moves through QX with QX's fee and no lock.

Failure modes:
- **Dropped transactions.** NFT operations ride `SimChain`'s queue with
  1–3 ticks of latency, reordering and the arena's 2% drop rate.
- **Insufficient funds.** The node drops a transaction whose attached amount
  exceeds the balance. The market rejects a bid that cannot pay its escrow
  (`INSUFFICIENT_FUNDS`).
- **Rule violations.** The market rejects a transfer while the fighter is
  locked or the share is reserved.

Escrow is an external balance (the market's escrow identity), so total QU
stays conserved. `invariants.check` asserts four things:
- escrow equals the open bids;
- every ask is its holder's;
- names are valid and unique;
- the contract's owner table equals the ledger's owners.

### 5.3 The Qubic backend (stub) and what it still needs

`QubicFighterNFTs` implements the port by building the real QX transaction for
each write, then raising `NetworkDisabled` with that plan. No flag enables
sending; turning it on is a code change.
- Reads raise `NotConnected` naming the exact query.
- The live arena refuses to start with `nft_backend: qubic`.

There are two realizations, and the owner picks one:

1. **QX assets.** Issue one asset per fighter through QX, then trade on QX.
   It works with today's contracts and tools.
   - No royalty, and no contest lock: R4 is then advisory, and the contract's
     ownership snapshots still keep payouts correct.
   - Issuance costs 1,000,000,000 QU per fighter on QX, on testnet too (a whole
     pre-funded testnet seed) and about $950 per fighter on mainnet.
2. **QDOJO-managed assets (what the simulation models; recommended for
   testnet and mainnet, see [the ecosystem research](research/qubic-nft-ecosystem-2026-09-30.md) §6).** The QDOJO contract
   issues the assets (it is then their issuer and manager) and runs the book in
   §3 with the lock and the royalty. It needs new contract procedures. The
   proposed opcodes 20–27 (`NftIssue` … `NftAnchor`) are listed in
   `nft_qubic.QDOJO_PROCEDURES`. Owners can still move a share to QX (R4
   covers that case). A contract that issues its own assets pays no QX
   issuance fee. QX never lets another contract take an asset, offers no fee
   when an owner moves one from QX to QDOJO (so QDOJO must ask none), and
   QDOJO pays 100 QU to release one back to QX.

QBAY is the third option. Its royalty and URI match the need and QubicBay is
the only place Qubic NFTs show with images today, but QBAY records are not
assets (no lock, no owner/possessor split) and QBAY cannot be enabled on a
fresh testnet (its operator is hard-coded to mainnet). It is a later, optional
listing track: see [the ecosystem research](research/qubic-nft-ecosystem-2026-09-30.md) §6.

What the Qubic backend still needs, in order:
1. **Protocol.** AdminRegisterAsset must carry the asset (issuer, name).
   `contracts/qubic/QDOJO.h` binds a fighter to issuer = fighter_id with name
   `QDOJOF` as an interim. No one holds a fighter_id's private key, so that
   asset can never be issued. It must become the token's real issuer and name.
2. **Signing and sending.** Sign with `qdojo.qubic.tx.Transaction.sign` and
   broadcast with `qdojo.qubic.node.Node.broadcast` (or POST
   `/v1/broadcast-transaction`), targeting the current tick + ~10. The riddle
   game's `chain/native.py` wrapper that did this was removed with the riddle
   code (tag `riddle-v0-final`) and is the model to restore.
3. **Confirmation.** `Node.tick_transactions(tick)`, hashed with K12, shows inclusion. Then
   re-read the effect (owner, orders) to learn success, and resend when the
   transaction was dropped.
4. **Reads.**
   - Ownership: `Node.asset_records(qubic.contracts.ownerships_request(issuer, name))`.
   - Possession: the same with `possessions_request`.
   - Books: QX functions 2–5 via `querySmartContract`.
   - History and sales: an indexer of QX trade logs.
5. **Live fees.** Read QX `Fees` (function 1) before any write.
6. **Realization 2 only.** Implement the QDOJO procedures and port
   `AssetLedger` into `QDOJO.h`, with parity tests against journals that
   contain `nft` records.

## 6. Public data

- **Export.**
  - `nfts.json` (schema `qdojo.combat.nfts.v1`): the collection (issuer,
    policy, frozen-art pointer), stats, and every token with its fighter name,
    rating, lock, ask, best bid, last sale and frozen hashes.
  - `nfts/<fighter_id>.json`: one token plus its order book, full provenance
    and sales.
  - `market.json`: listings and recent sales.
  - Each fighter's `asset` block in `index.json`: the ownership history the
    fighter page shows.
- **Read API** ([api.md](api.md) §3.2):
  - `GET /api/v1/nfts?owner=&for_sale=1&sort=serial|price|last_sale&page=`
  - `GET /api/v1/nfts/<fighter_id>` (the token, `book`, `history`, `sales`).
  - `/api/v1/market` and `/api/v1/owners/<id>` now read the same ledger.
- **Read model.** Tables `nft_tokens`, `nft_orders` and `nft_events`, plus
  `ownership` and `sales`, are all rebuilt from the journal's `nft` records.
  Following incrementally gives the same rows as a rebuild.
- **Site.**
  - `#collection`: a grid filtered by kit, finish and for-sale, sortable by
    ask or last sale.
  - `#nft/<fighter_id>`: card art, owner, possessor, manager, creator, traits,
    bio, the order book, provenance and sales. It also shows the frozen-art
    status, checked by re-hashing the card in the browser.
  - The fighter page links to its token.
  - The site offers no wallet actions. A HOW TO BUY box, worded from the
    export's `deployment.kind`, says plainly that nothing can be bought on
    the devnet and what buying will be on testnet and mainnet.

## 7. Frozen art and metadata

`qdojo combat nft freeze --arena DIR [--export DIR] --out OUT` replays the
arena's journal read-only for the token list. `scripts/nft-freeze.cjs` (node,
no packages) then writes, per token:
- the 64×64 card SVG and 48×48 sprite SVG from `apps/web/avatars.js`;
- lossless PNG masters at 16×: 1024 px card and 768 px sprite, indexed
  colour, nearest neighbour;
- metadata JSON in the common NFT shape:
  - `name`, `description` (the bio, plus how the art is made), `image`,
    `image_sha256` and `external_url`;
  - `attributes` from the traits;
  - `properties`: fighter_id, asset, renderer version and hash, and every
    file with its SHA-256.

Every file is stored as `OUT/objects/<sha256>.<ext>`. `OUT/manifest.json`
lists each token's files, the renderer version and its SHA-256, the pixel
hashes, the visual duplicates (identical sprite pixels) and a `root` hash over
the token list. The output is byte-for-byte reproducible.

`qdojo combat nft verify OUT` checks four things:
- every object hashes to its name;
- the renderer still draws each SVG byte for byte;
- each PNG decodes to exactly those pixels;
- the bio and traits are unchanged.

A changed renderer fails the check: previously frozen art must never silently
change (AUD-009). A test verifies the committed sample set
(`apps/web/data/nft/v1/sample/`, 9 tokens, about 450 KB).

The issuer can record a manifest's root on the ledger with the `anchor`
operation. The anchor proves which art set was released.

**Hosting (Proposal).**

| Option | For | Against |
|---|---|---|
| The site, `/data/nft/v1/<set>/` (now) | Free; content-addressed paths never change | One operator; gone if the site goes |
| IPFS (pinned by us and a pinning service) | Content addressing matches ours; marketplaces understand `ipfs://` | Pinning costs; metadata must be re-frozen with `ipfs://` URIs, because the image URI is inside the hashed metadata |
| Cloudflare R2 (or S3) with immutable object keys | Cheap, fast, fits the current Cloudflare setup | Trust in one provider; not content-addressed by the protocol |

Recommendation:
- Testnet: the site, as now.
- Before mainnet: IPFS for masters and metadata, mirrored on the site, with
  the manifest root anchored on chain.
- QBAY's per-NFT URI is at most 59 bytes: a bare CIDv1 fits exactly, as every
  QubicBay NFT stores it; `ipfs://<CIDv1>` (66 bytes) does not. A Qubic asset
  has no URI field, so the mapping from asset to metadata is the anchored
  manifest.

## 8. Journal, replay and restarts

- **Journal records.** Every executed NFT operation is one journal record:
  `{"k": "nft", "t", "who", "op", "args", "amount", "code"}`. Replays
  (`World.replay`, `devnet.apply_records`, `readmodel.Replica`) re-execute it
  and stop if the result code differs.
- **Deferred sales.** These settle inside `World.end`, so every replay
  reproduces them from the `end` record.
- **Owner records.** Ownership changes also write `owner` records. The C++
  ports read those and skip `nft` and `xfer` records.
- **Snapshots.** The ledger is part of the devnet snapshot, and `nft.py` is
  in the snapshot code fingerprint.
- **Migrating an older arena.** Its `assets.json` is imported once. Each asset
  is minted to its current owner, with the old history as provenance.

## 9. Decisions for the owner

| # | Decision | Proposed |
|---|---|---|
| 1 | R1–R6 above | Accept as written |
| 2 | Market fee / royalty / gift fee | 250 bps / 250 bps / 100 QU |
| 3 | Testnet realization | QDOJO-managed assets (5.3 option 2), QX as the secondary market; QBAY listing later ([the ecosystem research](research/qubic-nft-ecosystem-2026-09-30.md)) |
| 4 | Asset names | `QF` + base-36 serial; issuer = one dedicated collection identity |
| 5 | Hosting | Site now; IPFS + site mirror + on-chain anchor before mainnet |
| 6 | Licence and rights (R7), supply and allocation (AUD-009) | Open: needs owner and legal review |
