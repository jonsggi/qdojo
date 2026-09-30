# Qubic NFT ecosystem and licensing norms: research for QDOJO

> **Date:** 2026-09-30 \
> **Scope:** research only. Nothing was minted, sent or changed. \
> **Inputs read first:** `docs/nft.md`, `docs/testnet.md`, `apps/web/AVATARS.md`, `audits/issues/AUD-009*`, `AUD-010*` and `AUD-028-licence.md` (qdojo `main` at `11e74015`), plus the earlier copies in `scratchpad/round3/nft/research/`. \
> **Primary source pin:** qubic/core `main` at **`e3ef766`** (release v1.305, merged 2026-09-23). The last commit touching each file: `src/contracts/Qbay.h` `c07faa8` (2026-06-22), `src/contracts/Qx.h` `ff681a1` (2026-03-09), `src/contract_core/contract_def.h` `a18fe35` (2026-09-21), `src/contracts/QTREAT.h` `fd774c2` (2026-09-21), `doc/contracts.md` `17aef01` (2026-08-28), `LICENSE.md` `7ae5a13` (2025-07-15). Copies are in `scratchpad/round3/research/src/`. \
> **Live reads:** `rpc.qubic.org` on 2026-09-30 around 09:15 UTC: epoch 232, tick about 82,255,767. \
> **Confidence markers:** **[src]** read in source; **[live]** read from mainnet or a live API today; **[doc]** official docs or blog; **[2nd]** secondary or search summary; **UNCERTAIN** means not verified.

## Executive summary

1. **Qubic has two NFT representations, and they are not interchangeable.**
   - **QBAY records.** QBAY is contract 12, the NFT marketplace. Its NFTs are rows in QBAY's own state, not Qubic assets. Each row holds a creator, a *possessor* (there is no separate owner), a royalty, a URI of at most 59 bytes and sale, offer and auction status. QubicBay.io is the only front end, and the only place Qubic NFTs appear **with images**. **[src][live]**
   - **1-share Qubic assets** (issuer plus name). These show in the official wallet and explorer as tokens, without images. They trade on QX UIs. We found **no collection using them as NFTs**, and no NFT standard or proposal for them. **[src][2nd]**
2. **QBAY is the de facto standard.** It holds 20 collections and 5,796 NFTs minted on chain **[live]**. The metadata convention is a **bare CIDv1** (exactly 59 characters, no `ipfs://` prefix) pointing to OpenSea-style JSON with `name`, `description`, `image` and `attributes` **[live]**. Royalties are enforced only on QBAY sales, not on free transfers. The contract caps royalties at 97%; the UI caps them at 10%. Fees are 2% to the marketplace and 1% to shareholders **[src]**.
3. **Three corrections for `docs/nft.md`:**
   - `ipfs://<CIDv1>` is 66 bytes and **does not fit** QBAY's 59-byte URI. Store the bare CID, as every QubicBay NFT does.
   - QBAY NFTs have no owner/possessor split and no managing contract. They are not assets.
   - QX issuance is not "free on testnet". It costs 10⁹ testnet QU, which is an entire pre-funded seed (about 1 billion QU each).
4. **Costs today [live][src]:**
   - QX issuance: 10⁹ QU per asset. That is about **$950 per fighter** at QBAY's oracle rate of 1,052,631 QU/USD, which rules QX out for large mainnet supplies.
   - QBAY: a collection costs $100 (up to 200 NFTs) or $200 per 1,000 NFTs, paid in CFB and burned. Minting into your own collection costs 0 QU; a single mint costs 5,000,000 QU. Transfers cost nothing.
   - `qpi.issueAsset` called from our own contract: **no QX fee**, only execution-fee reserve.
5. **QDOJO can do everything itself.** Once in Core, QDOJO's index will be above 12, and a contract may call any contract with a lower index. So it can:
   - issue its own 1-share assets (issuer = the contract or the invoking user) and be their managing contract (hard contest lock, own royalty);
   - accept assets released from QX, and release them back to QX;
   - read QBAY possession, and even call QBAY procedures.

   **QTREAT** (contract 30, constructed in epoch 233, which starts today) is a live precedent: it reads QBAY NFT possession from inside a contract and re-checks it every epoch **[src]**.
6. **Testnet:**
   - The public testnet RPC returned **HTTP 522 today** **[live]**. The testnet explorer page loads.
   - The faucet is a Discord bot. Pre-funded seeds hold about 1B QU each **[doc]**.
   - QX runs anywhere Core runs.
   - **QBAY is effectively unusable on a fresh testnet or devnet.** Its marketplace owner and the CFB issuer are hard-coded mainnet identities, and minting stays disabled until that owner switches the marketplace on **[src]**, inferred and **not tested**.
7. **Recommendation: (d) a hybrid.**
   - The canonical fighter token is a **QDOJO-issued, QDOJO-managed 1-share asset**. This gives a hard lock, a royalty in QDOJO's own book, no QX fee, a native wallet and explorer presence, and it works on testnet.
   - An owner can move a token to QX for liquidity, as in the current design.
   - Metadata is frozen as bare CIDs plus an anchored manifest.
   - QBAY is a **later, optional** track. Its UI requires QBAY records, so it would need either a QBAY-native mirror (with the lock approximated by snapshots or escrow) or QubicBay indexing our assets off chain. Ask the QubicBay team.
   - If collector visibility on QubicBay matters more than the lock, the alternative is **(b) QBAY-first**, with snapshots (and optional escrow) instead of a lock. §6 lays out the trade.
8. **Licensing:**
   - qubic/core uses the custom **"Anti-Military License"**: an MIT-style grant plus field-of-use bans on military uses. Its first ban lists "melee weapons" and military-strategy software. **Confirmed**; it is not OSI-open. The core repo also ships some MIT code.
   - A contract enters Core by a PR to `qubic/core` plus a published proposal containing the **final source**. No CLA was found, so QDOJO.h will in practice be distributed under the core licence. Keep it compatible: offer QDOJO.h under **MIT, or MIT plus the Anti-Military License**.
   - Norms elsewhere: code MIT/Apache/GPL (Nouns and Dark Forest are GPL-3.0). Art is CC0 (Nouns), a16z **Can't Be Evil** (six variants), or Dapper **NFT License 2.0**.
   - QubicBay records a per-collection licence label off chain: EXCLUSIVE, NON_EXCLUSIVE, COMMERCIAL or PERSONAL. 13 of the 19 listed collections use NON_EXCLUSIVE.

---

## 1. NFT standards on Qubic today

### 1.1 Representation A: QBAY records (the de facto NFT)

The contract is `src/contracts/Qbay.h` (`c07faa8`), contract index 12, constructed in epoch 154 (`contract_def.h`: `{"QBAY", 154, …}`, "proposal in epoch 152, IPO in 153"). **[src]**

**Data model [src]:**
- `InfoOfNFT` (238 bytes) has these fields: `creator`, `possessor`, `askUser`, `creatorOfAuction`, `salePrice`, `askMaxPrice`, `currentPriceOfAuction`, auction start and end times, `royalty` (a percentage), `NFTidForExchange`, `URI` (`Array<uint8,64>` of which only **59 bytes** are kept, `QBAY_LENGTH_OF_URI = 59`), and sale, ask, exchange and auction status bits.
- **There is no owner/possessor split and no managing-contract field.** The NFT ID is a global sequential index, so it cannot be chosen.
- Capacity is global across all creators: `QBAY_MAX_NUMBER_NFT = 2,097,152` NFTs and `QBAY_MAX_COLLECTION = 32,768` collections.
- `InfoOfCollection` (112 bytes) holds `creator`, `priceForDropMint`, `maxSizeHoldingPerOneId`, `currentSize`, a 59-byte `URI`, `royalty` and `typeOfCollection` (0 = drop, 1 = normal).

**Procedures [src]**, from `REGISTER_USER_FUNCTIONS_AND_PROCEDURES`:

| # | Procedure | Behaviour |
|---|---|---|
| 1 | `settingCFBAndQubicPrice` | Marketplace owner only. Sets the CFB and QU per USD "oracle" |
| 2 | `createCollection` | `volume` 0 means 200 NFTs; 1–10 means 1,000 × volume. The fee is $100 for 200 or $200 × volume, paid in **CFB** at `priceOfCFB` and sent to `NULL_ID` (burned). The marketplace owner pays nothing. Royalty ≤ `QBAY_MAX_ROYALTY_PERCENT` = 97 |
| 3 | `mint` | Into your own normal collection: **0 QU**; creator and possessor = the invocator; the royalty is the collection's. Single NFT without a collection: **5,000,000 QU** (`QBAY_SINGLE_NFT_CREATE_FEE`) with its own royalty. Refused while `statusOfMarketPlace == 0` |
| 4 | `mintOfDrop` | Public mint from a drop collection at `priceForDropMint`, which is paid to the creator. A per-ID holding cap applies |
| 5 | `transfer` | **Free.** It refunds the attached QU. The possessor only; refused while listed, in an exchange or before an auction ends |
| 6–8 | `listInMarket`, `buy`, `cancelSale` | Fixed-price sale |
| 9–10 | `listInExchange`, `cancelExchange` | NFT-for-NFT swap |
| 11–13 | `makeOffer`, `acceptOffer`, `cancelOffer` | Offers |
| 14–15 | `createTraditionalAuction`, `bidOnTraditionalAuction` | Auctions, timed by wall-clock `qpi.year()…second()` |
| 16 | `TransferShareManagementRights` | For the CFB asset. Fee `transferRightsFee` = 100 QU after `BEGIN_EPOCH` |
| 17 | `changeStatusOfMarketPlace` | Marketplace owner only. Switches create and mint on or off |

Functions 1–9: `getNumberOfNFTForUser`, `getInfoOfNFTUserPossessed`, `getInfoOfMarketplace`, `getInfoOfCollectionByCreator`, `getInfoOfCollectionById`, `getIncomingAuctions`, `getInfoOfNFTById`, `getUserCreatedCollection`, `getUserCreatedNFT`. **[src]**

**Fees and royalty on a QU sale** (`buy`) **[src]:**
- creator royalty = `price × royalty / 100`, paid to `creator` **even when the creator is the seller**;
- market fee = 2% (`QBAY_FEE_NFT_SALE_MARKET = 20`/1000);
- shareholder fee = 1% (`…_SHAREHOLDERS = 10`/1000);
- the seller gets the rest.

On a CFB-paid sale there is the 2% market fee plus the royalty, but **no shareholder fee**. At `END_EPOCH`, shareholder fees are distributed to the 676 shares and the earned QU and CFB go to `marketPlaceOwner`.

**Governance and centralisation [src]:**
- `marketPlaceOwner` and `cfbIssuer` are hard-coded identities in `INITIALIZE`.
- The owner sets the price oracle and can pause creation and minting.
- Upgrades go through computor proposals. Example: `qubic/proposal` `SmartContracts/2026-06-18-Qbay-Upgrade.md`, which made collection CFB fees burn and whose core PR is #922. **[doc]**

**Live state [live]:** `getInfoOfMarketplace` (function 3) on 2026-09-30 returned:
- `priceOfCFB` = 454,000 CFB/USD;
- `priceOfQubic` = 1,052,631 QU/USD;
- `numberOfNFTIncoming` = 26,600 (reserved by collections);
- `earnedQubic` this epoch = 116,310,000 QU;
- `numberOfCollection` = 20; `numberOfNFT` = 5,796; `statusOfMarketPlace` = 1.

### 1.2 Representation B: 1-share Qubic assets

- An asset is (issuer, name). The name has at most 7 characters: A–Z first, then A–Z or 0–9. **[src]** `doc/contracts.md` "Assets and shares"; `src/qpi/impl/qpi_assets_impl.h` `issueAsset`.
- Ownership and possession records each name a **managing contract**. Only the manager can move shares (`transferShareOwnershipAndPossession` checks `managingContractIndex == _currentContractIndex`). **[src]**
- Each issuance uses **3 universe entries**: ISSUANCE, OWNERSHIP and POSSESSION (`src/assets/assets.h`). The universe is chain-wide, `ASSETS_CAPACITY = 0x1000000` (16.7M entries) (`src/network_messages/common_def.h`). **[src]**
- Visibility:
  - The official wallet-app lists assets with "Issued by" and "managed by" (`qubic/wallet-app` `lib/l10n/app_en.arb`).
  - The explorer has "Assets" and "Assets Rich Lists" (`qubic/explorer-frontend` `public/locales/en/network-page.json`).
  - Neither has NFT or image strings: a GitHub code search of `qubic/wallet-app`, `qubic/wallet`, `qubic/qubic-mm-snap` and `qubic/explorer-frontend` for "nft" and "qbay" finds only a QBAY contract-address constant in the explorer. **[src]**
- No collection or project was found using 1-share assets as NFTs. **UNCERTAIN**: the search was limited to the QubicBay API, the qubic.org ecosystem, GitHub and web search.

### 1.3 Is there a standard or proposal?

- No NFT token standard (an ERC-721 analogue) exists in `qubic/core` `doc/` or `qubic/proposal` `SmartContracts/`. The directory lists 29 proposals up to `2026-09-18-qtreat_sc_proposal.md`; the only NFT-related ones are `2025-03-11-Qbay.md` and `2026-06-18-Qbay-Upgrade.md`. **[src]**
- A GitHub issue search of `qubic/core` for "NFT" returns only the QBAY PR (#321), QTREAT (#973) and an unrelated oracle PR. **[src]**
- **In practice, QBAY's `getInfoOfNFTById` is what other contracts integrate against (QTREAT, §3).**

### 1.4 Metadata

- **On chain:** a URI of at most 59 bytes. **[src]**
- **In practice [live]:** QubicBay writes the **bare CIDv1** (base32, `bafkrei…`), which is exactly 59 characters. Verified on chain: NFT 5795's URI is `bafkreiehy5idpkf2qtqk2u52ufvq265t2vcvxsuxejekt6xoacspacg4hq` (via `querySmartContract` contract 12, function 7). That CID resolves to OpenSea-style JSON: `name`, `description`, `image` (here an `https://ipfs.io/ipfs/<dir-CID>/<file>.png` URL) and `attributes: [{trait_type, value}]`.
- `ipfs://` plus a CIDv1 is **66 bytes and would be truncated**. A CIDv0 (`Qm…`, 46 characters) plus `ipfs://` would fit (53 bytes), but QubicBay's own flow uses CIDv1.
- QubicBay's front end uploads through **Pinata** (`api.pinata.cloud`, `pinFileToIPFS` and `pinJSONToIPFS` in `qubicbay.io/assets/index-6fc064c1.js`). It reads through a gateway fallback list: `w3s.link`, `cloudflare-ipfs.com`, `gateway.pinata.cloud`, `ipfs.io` and a configurable default. It also keeps an off-chain DB (`api.qubicbay.io/v1/collections`, `/v1/nfts`) with names, descriptions, traits and licence labels. **[live]**
- **Lesson.** `ipfs.io`, `dweb.link` and `w3s.link` now answer "switching to a service worker gateway only" for raw fetches. Only `gateway.pinata.cloud` served the JSON today **[live]**. Put `ipfs://` inside the metadata's `image` field, not a hard-coded gateway URL.

## 2. Marketplaces, wallets and explorers

| Venue | Qubic NFTs? | Images? | Royalties? | Source |
|---|---|---|---|---|
| **QubicBay.io** (QBAY front end) | Yes: QBAY records only | Yes, from IPFS through gateways (Pinata first) | Yes, QBAY on-chain royalty. The UI limits creators to 0–10% | bundle `index-6fc064c1.js`; `api.qubicbay.io/v1/*` **[live]**; qubic.org blog 2025-10-13 **[doc]** |
| qx.qubic.org, QubicTrade, QXBoard, QubicSwap (QX UIs) | Assets only (any share count) | No images, token lists | No royalty in QX (0.3% trade fee to QX shareholders) | web search **[2nd]**; `Qx.h` **[src]** |
| Official wallets (web wallet.qubic.org, mobile/desktop wallet-app) | Assets (issuer, "managed by"). No QBAY NFT view found | No | n/a | `qubic/wallet-app` l10n **[src]**. QubicBay's blog lists these wallets as the way to *connect* **[doc]** |
| MetaMask snaps (`qubic/qubic-mm-snap` "Qubic Connect"; `ardata-tech/qubic-wallet`) | Signing and broadcast only. No NFT code found | No | n/a | GitHub search **[src]** |
| explorer.qubic.org | Assets, rich lists; QBAY is a named contract | No | n/a | explorer-frontend CHANGELOG ("add Qbay smart contract to qubic constants") **[src]** |
| qubic.li, qubic.tools, qfront.org | Execution-fee and asset analytics | No NFT views found (**UNCERTAIN**) | n/a | `doc/contracts.md` monitoring links **[doc]** |

**Bottom line:** images and royalties exist in one place, QubicBay, and only for QBAY records. A QDOJO-managed asset would appear in wallets and explorers as a token named like `QF00001`, issued by QDOJO and managed by QDOJO, with no picture. It may also **not be sendable from the wallet's Send button** if that button routes through QX. **UNCERTAIN**: not tested.

## 3. Existing projects

These are the QubicBay collections from `GET https://api.qubicbay.io/v1/collections` on 2026-09-30 **[live]**. The API lists 19; the chain says 20, and ID 14 is missing from the API.

| ID | Collection | Type | Declared size | Royalty | Licence label | Trades | Lifetime trade volume (QU) | Created |
|---|---|---|---|---|---|---|---|---|
| 0 | Qbros (CFB team) | drop | 1001 | 5% | NON_EXCLUSIVE | 1,345 | 9.99 B | 2025-09-10 |
| 1 | Qub3s | drop | 676 | 4% | NON_EXCLUSIVE | 947 | 23.8 B | 2025-10-07 |
| 4 | **Garth: The Source Code** (gaming category) | drop | 200 | 10% | NON_EXCLUSIVE | 480 | **58.3 B** | 2025-10-20 |
| 15 | **QDoge NFTs 1.0** (used by QTREAT dividends) | drop | 200 | 10% | NON_EXCLUSIVE | 467 | 25.3 B | 2026-02-20 |
| 16 | $0.01 Cypherpunks | drop | 200 | 10% | NON_EXCLUSIVE | 367 | 52.8 B | 2026-03-15 |
| 17 | **BITE: Ocean Rebels** (game) | drop | 200 | 5% | COMMERCIAL | 33 | 3.24 B | 2026-04-06 |
| 19 | **BITE: Ocean Elements** (in-game utility) | drop | 200 | 10% | PERSONAL | 6 | 0.36 B | 2026-09-29 |
| … | 12 more (Quties, piQcells, Misfit Bears 5,000, COINS, Aigarth and Anna series, Hall of Fame, QMarks, Qvent) | mostly drop | 200–5,000 | 3–10% | mostly NON_EXCLUSIVE | | | |

**Totals across 19 collections:** 218,994,280,003 QU of `totalTradeVolume`. That is **about $208k** at QBAY's oracle rate. **UNCERTAIN**: the rate is set by the marketplace owner, and it is unclear whether the figure includes primary drop mints. The `currentSize`, `volume` and "left" fields in the API do not map cleanly to the contract fields (a declared 676 is not a contract volume option), so treat supply figures as creator-declared.

**Gaming precedents:**
- **QTREAT** (`src/contracts/QTREAT.h` `fd774c2`, contract 30, construction epoch 233; proposal `qubic/proposal` `SmartContracts/2026-09-18-qtreat_sc_proposal.md`) **[src]**:
  - "Qdoge ASIC (NFT 2.0)" parts are QBAY NFTs. `RegisterAsic` calls `CALL_OTHER_CONTRACT_FUNCTION(QBAY, getInfoOfNFTById)` and requires `possessor == invocator`.
  - "Every registered rig and every dividend NFT is re-checked against QBAY in every END_EPOCH … a sold asset stops paying its previous owner in the epoch it is sold."
  - The dividend NFT IDs (4968…) are hard-coded in `INITIALIZE`.
  - **This is the model for "QBAY NFT plus our contract reads possession, no lock".**
- **BITE 'em All** (biteonqubic.com): QBAY drop collections with in-game multipliers and use rights. The page gives no detail on how the game verifies ownership (**UNCERTAIN**, probably off chain via wallet connect). Its supply is designed as 8 types × a 25-item rarity ladder = 200. **[live]**
- **Other gaming or social contracts in Core**, none of which use NFTs: QDUEL (23), GGWP/WolfPack (28), QUSINO (26), QRAFFLE (19), RL (16). **[src]** `contract_def.h`.

**Lessons:**
1. Collections are small: 200 is the default and cheapest tier, and most volume sits in 200-piece drops.
2. Royalties of 3–10% are the norm, and the UI caps them at 10%.
3. QubicBay is the discovery surface.
4. Contracts integrate by reading QBAY possession, not by locking.
5. Off-chain licence labels are common but not on chain.
6. Pinning discipline matters, because public IPFS gateways are degrading.

## 4. Costs and constraints

### 4.1 Minting and issuance

| Route | Cost | Limits | Source |
|---|---|---|---|
| QX `IssueAsset` | **1,000,000,000 QU per asset**, paid to QX shareholders (about $950 at the oracle rate) | Any share count; name ≤ 7 characters | `Qx.h` INITIALIZE; live `Fees` = (1e9, 100, 3,000,000) **[src][live]** |
| QX transfer | 100 QU | | same |
| QX trade | 0.3% from the seller (`price·shares·3e6/1e9 + 1`) | | same |
| `qpi.issueAsset` from our contract | **No QX fee**; only execution time and the state digest from our fee reserve | Issuer must be **the contract itself or the invocator** (`issuer != _currentContractId && issuer != _invocator` → 0). `doc/contracts.md` warns issuers may later "pay for entries in the ledger" | `qpi_assets_impl.h` **[src]**; `doc/contracts.md` |
| QBAY collection | $100 (≤ 200) or $200 × k (k × 1,000, k ≤ 10), paid in **CFB and burned**. Mints into it cost 0 QU | Global cap of 2,097,152 NFTs (26,600 reserved today) | `Qbay.h`; 2026-06-18 upgrade proposal **[src][doc]** |
| QBAY single mint | 5,000,000 QU | | `Qbay.h` **[src]** |
| QBAY transfer | 0 | | `Qbay.h` **[src]** |

### 4.2 Deploying QDOJO as a Core contract

From `doc/contracts.md` "Development", "Review and tests" and "Deployment" **[src]**:
1. PR to `qubic/core` `develop`, adding a `contract_def.h` entry at the **next free index (31 today)**.
2. Pass `qubic/contract-verify`, GoogleTest coverage, a core-dev review (style and dialect only; "the contract devs are solely responsible for the correctness"), and a multi-node testnet run.
3. Put the proposal text **with the final source code** in `qubic/proposal/SmartContracts`.
4. A computor files a GQMPROP proposal in epoch N, with at least 451 votes and yes > no.
5. Epoch N+1: code included; the **IPO** runs as a Dutch auction of 676 shares, and the proceeds are **burned into the execution-fee reserve** (`reserve = finalPrice × 676`, `doc/execution_fees.md`).
6. Epoch N+2: construction. If the IPO fails, the contract is unusable.

**Execution fees [src]** (`doc/execution_fees.md`):
- Procedures and state-digest recomputation drain the reserve.
- Refill with `qpi.burn` or QUTIL `BurnQubicForContract`.
- A contract with a reserve ≤ 0 skips `BEGIN_TICK`/`END_TICK` and refuses user procedures.
- Charge invocation rewards and burn part of them.
- QBAY's IPO burned about 89.3 B QU (about $104k). **UNCERTAIN**: from a search summary, not a primary source.

**Timing [src][live]:**
- An epoch is one week and ends **Wednesday 12:00 UTC**.
- `TARGET_TICK_DURATION` is 1000 ms (`src/public_settings.h`).
- Measured today: epoch 232 began at tick 81,400,000, and tick 82,255,767 was reached about 6.9 days later, which is **about 0.7 s per tick**.

### 4.3 Can QDOJO create, transfer or manage assets or QBAY items itself?

- **Calls between contracts.** "Procedures can call procedures and functions of the same contract and of contracts with lower contract index." (`src/contracts/README.md`). With index ≥ 31, QDOJO can invoke QX (1) and QBAY (12). They can never call QDOJO, except through system callbacks. **[src]**
- **Its own assets.** `qpi.issueAsset(name, SELF or invocator, 0, 1, 0)`, then QDOJO is the managing contract and alone moves the shares with `qpi.transferShareOwnershipAndPossession`. **This is the hard contest lock and a royalty QDOJO can enforce.** **[src]**
- **Management rights.** These are `qpi.releaseShares` (push) and `qpi.acquireShares` (pull). Each goes through the counter-party's `PRE_ACQUIRE_SHARES`/`PRE_RELEASE_SHARES` callback (allow and requested fee), then `POST_*`. An undefined callback rejects. **[src]** `doc/contracts.md` "Management rights transfer".
  - **QX → QDOJO:** the owner calls QX `TransferShareManagementRights` (procedure 9; it takes no fee itself), which releases with an **offered fee of 0**. QDOJO's `PRE_ACQUIRE_SHARES` must therefore request 0, or the transfer fails. Reserved (ask-listed) shares cannot be released. QX **always rejects `acquireShares`**, so QDOJO cannot pull. **[src]** `Qx.h` 1084–1113, 1167–1185.
  - **QDOJO → QX:** QDOJO calls `releaseShares(…, QX_INDEX, …, offeredFee ≥ 100)`. QX's `PRE_ACQUIRE_SHARES` requests `_transferFee` (100 QU) from QDOJO's balance. **[src]**
  - `doc/contracts.md` recommends release only on the owner's request, with `PRE_RELEASE_SHARES` checking `qpi.originator()`, so that no contract can "hijack" rights. This fits R4: release only when the fighter is IDLE.
  - Input layout: `TransferShareManagementRights_input {Asset{id issuer; uint64 assetName}; sint64 numberOfShares; uint32 newManagingContractIndex}` is 52 bytes of fields, **56 with C++ 8-byte alignment**. This resolves the "padding uncertain" note in `docs/nft.md` §5.1, as a likely answer, **not byte-tested**.
- **QBAY items.**
  - QDOJO can read `getInfoOfNFTById` (as QTREAT does).
  - QDOJO can invoke QBAY procedures as itself. It could hold NFTs in escrow (a player `transfer`s the NFT to QDOJO's ID for free; QDOJO later `transfer`s it back) and could even mint into a collection it created itself. Creating one needs CFB possessed by QDOJO and managed by QBAY. Minting in a house-created collection must be done by the house identity, because the collection creator must equal the invocator.
  - QBAY offers **no hook to block a transfer or sale**, so the only hard lock is escrow. Escrow costs two extra transactions per contest and fails if the NFT is listed.
  - Every such call needs QBAY's fee reserve to be positive (`CallErrorInsufficientFees` otherwise). **[src]**

## 5. Testnet

- **RPC:** `https://testnet-rpc.qubic.org` (docs.qubic.org/developers/testnet-resources) **[doc]**. It returned **HTTP 522 (Cloudflare origin unreachable) on 2026-09-30** **[live]**, consistent with `docs/testnet.md` marking it UNCONFIRMED.
- **Explorer:** `https://testnet.explorer.qubic.org/` responds with HTTP 200 **[live]**. The mainnet explorer is `explorer.qubic.org`.
- **Faucet:** a Discord `#bot-commands` bot. Pre-funded testnet seeds hold about 1 B QU each **[doc]**. The AIO **Qubic Dev Kit** runs a local core, faucet, wallet and RPC (docs.qubic.org/developers/dev-kit) **[doc]**.
- **QX:** compiled into every Core build, so it is present wherever Core runs. **Issuing one asset costs 10⁹ QU, i.e. a whole pre-funded seed.** Plan many seeds or faucet top-ups, or issue from QDOJO instead.
- **QBAY on testnet:** no official statement found. From source:
  - `INITIALIZE` hard-codes the mainnet `marketPlaceOwner` and `cfbIssuer`.
  - `statusOfMarketPlace` starts at 0, and while it is 0, `mint` is refused for everyone and `createCollection` for everyone except the owner.
  - So on a fresh testnet or devnet, **QBAY cannot mint unless the build patches the owner identity or state.** **UNCERTAIN**: inferred, not tested; a snapshot-based testnet could differ.
- **Testnet NFT tooling:** none found. The QubicBay front end is hard-wired to `rpc.qubic.org` and `api.qubicbay.io` (bundle constants), i.e. mainnet only. **[live]**

## 6. Recommendation for QDOJO

### 6.1 Trade-offs

| | (a) QX plain assets | (b) QBAY collection | (c) QDOJO-managed assets | (d) Hybrid: (c) + QX exit + frozen metadata (QBAY later) |
|---|---|---|---|---|
| **Royalty** | None | Yes, on QBAY sales only (free transfers bypass it) | Yes, in QDOJO's book (250 bps proposed) | Yes, while QDOJO-managed. None after exit to QX |
| **Contest lock (R4)** | None, advisory only | None. Snapshot payouts (QTREAT pattern) or escrow for 2 extra txs | **Hard lock** | Hard lock unless the owner exits while IDLE |
| **Marketplace visibility** | QX UIs, no images | **QubicBay with images**, the collector audience | Our site only. Wallets and explorers show a token without an image | Our site plus QX UIs. QubicBay only if QubicBay indexes our assets (ask them) |
| **Cost per fighter** | **10⁹ QU (≈ $950)** | ≈ $0.20–$0.50 per NFT in CFB; 0 QU mint; free transfer | Execution fee only (plus possible future ledger fees) | Same as (c); exit costs QDOJO 100 QU to QX |
| **Works on testnet or devnet** | Yes, 1 seed per asset | **No, without a patch** | Yes | Yes |
| **Complexity** | Lowest (the existing stub) | Moderate: inter-contract reads, escrow, a QBAY dependency, a centralised operator | High: order book, escrow, royalty and callbacks in QDOJO.h, all audited | High, but it matches what `combat/nft.py` already simulates |
| **Dependency risk** | QX (stable, index 1) | QBAY owner (pause and oracle), QubicBay off-chain DB | Our contract's fee reserve | Same as (c) |

### 6.2 Pick: (d) hybrid

1. **Canonical token.** One 1-share asset per fighter, issued by `qpi.issueAsset` inside QDOJO. Issuer = the QDOJO contract, or the house identity as invocator, so that all tokens share one issuer; name `QF`+base36. QDOJO keeps management, runs the §3 book with the lock and the royalty, and reads ownership from the core asset ledger, not from another contract's state.
2. **Exit and entry.**
   - `PRE_RELEASE_SHARES` refuses every pull.
   - An owner-invoked `NftToQx` releases to QX only when the fighter is IDLE; QDOJO pays QX's 100 QU and may charge the owner.
   - `PRE_ACQUIRE_SHARES` accepts returns from QX at fee 0, for QDOJO-issued assets only.
   - Payout snapshots keep a mid-contest QX sale safe, as `docs/nft.md` R4 already says.
3. **Metadata.**
   - Keep the frozen, content-addressed set (`docs/nft.md` §7).
   - Before mainnet, pin to IPFS with **bare CIDv1** references, and set `image` to `ipfs://…` inside the JSON.
   - Anchor the manifest root on chain. A QX-style asset has no URI field, so the anchor (plus a `fighter_id → CID` map in QDOJO state, or 32-byte digests) is the binding.
4. **QBAY track (optional, later).**
   - Open a conversation with the QubicBay team (Pepito, Poly, Serendipity per the qubic.org blog, 2025-03-19) about displaying QDOJO assets. Their catalogue is an off-chain DB, so indexing need not change the chain.
   - If that fails and visibility is decisive, switch to **(b) QBAY-first**: a normal collection of 200 or 1,000 (for $100–200 in CFB), house-minted at 0 QU, royalty ≤ 10%. QDOJO would read `getInfoOfNFTById` at registration and entry and snapshot the possessor for payouts. Escrow would be available for cups and title fights.
   - Accept the costs of (b): no universal lock, an owner-operated dependency, and no testnet.
5. **Testnet now.** Use (c) if QDOJO.h gains the NFT procedures in time. Otherwise use (a) with the caveat that each asset costs one pre-funded seed; issue only a handful.

Owner decisions this adds to `docs/nft.md` §9:
- visibility versus lock (choose (d) or (b));
- royalty ≤ 10% if QBAY compatibility matters;
- whether to approach QubicBay.

## 7. Licensing norms

### 7.1 qubic/core

- **`LICENSE.md` (`7ae5a13`)** is the **"Anti-Military License"**. It is an MIT-style permission grant ("perpetual, worldwide, non-exclusive, free of charge … use, copy, modify, merge, publish, distribute, sublicense, and/or sell") with four conditions:
  1. no use "in the military sphere and in relation to military products", with a list that includes "melee weapons" and "any software or hardware for determining strategies, reconnaissance, troop positioning, conducting military actions";
  2. no use in any connection to military activities, and users must take "reasonable actions" to ensure this;
  3. no use by entities connected to the military sphere;
  4. the restrictions carry to all modifications.

  Notice and warranty text follow, as in MIT. **The file has no copyright line.** **[src]**
- `LICENSE-MIT.md` and README §License: "licensed under the Anti-Military License. However, it includes some code licensed under the MIT License … used with permission and retains its original MIT license" (e.g. uint128_t). GitHub classifies the licence as "Other" / `NOASSERTION`. **[src]**
- It is **not an OSI open-source licence**: it discriminates by field of endeavour (OSD §6). This is analysis, not legal advice.
- Relevance to QDOJO: a robot-fighting *game* is not military use. The ban on "melee weapons" and military-strategy software is about real-world military products. Still, avoid positioning QDOJO's planners or engine as tactical or strategy software for any military purpose. **Legal review advisable.**

### 7.2 Ecosystem

- **Anti-Military License:** `qubic/qubic-cli`, `qubic/wallet`, `qubic/wallet-app`, `qubic/core-lite` (plus an MIT file), and `@qubic-lib` ts-library (`package.json`: "Qubic's Anti Military License").
- `qubic/contract-verify` ships MIT third-party code.
- **No licence file:** `qubic/explorer-frontend`, `qubic/qubic-http`, `qubic/qubic-mm-snap`, `qubic/proposal`.
- **None of the contract headers checked** (Qx.h, Qbay.h, QTREAT.h, GGWP.h, QDuel.h, Escrow.h) has a licence or SPDX header, so they fall under the repo licence. **[src]**, from GitHub API reads on 2026-09-30.

### 7.3 If QDOJO.h is compiled into qubic/core

- The contract **must** be contributed as `src/contracts/QDOJO.h` by PR to `qubic/core`, with tests in `test/`. The proposal must include "the final source code of the contract" (`doc/contracts.md` "Deployment" step 2). **The source is therefore necessarily public.** Only the header can go in: "Do NOT change any other file in the `src` folder without explicit permission." **[src]**
- No CLA or inbound-licence clause was found in `doc/contributing.md` or `README.md`. The practical norm is inbound = outbound: once merged, QDOJO.h is distributed as part of "the Software" under the Anti-Military License. **UNCERTAIN**: no explicit statement.
- Options:
  1. **Licence QDOJO.h under MIT**, keeping our copyright header. Core already carries MIT code alongside its licence, so this is the least friction and keeps the reference implementation reusable. **Recommended.**
  2. **Dual-license QDOJO.h under MIT OR the Qubic Anti-Military License**, making the merge unambiguous.
  3. Use a copyleft or source-available licence. This conflicts with Core's permissive distribution and is not recommended.

  Qubic contracts carry no headers, so ask the core devs whether an SPDX comment line is acceptable (**UNCERTAIN**).

### 7.4 NFT game norms: code versus art

| Project | Code | Art | Source |
|---|---|---|---|
| Nouns | GPL-3.0 (`nounsDAO/nouns-monorepo`) | **CC0** (public domain), with derivative ecosystems (Lil Nouns etc.) | GitHub API; nouns101.wtf/glossary/cc0 **[src][2nd]** |
| Dark Forest | GPL-3.0 (`darkforest-eth/darkforest-v0.6`) | n/a (procedural) | GitHub API **[src]** |
| CryptoKitties / Dapper | proprietary | **NFT License 2.0** (nftlicense.org): holder commercial use up to $100k/yr | Dapper Labs Medium; crypto.news **[2nd]** |
| a16z "Can't Be Evil" (2022-08-30) | MIT (`a16z/a16z-contracts`) | Six licences: **PUBLIC** (CC0), **EXCLUSIVE** (exclusive commercial, creator keeps nothing), **COMMERCIAL** (non-exclusive, creator keeps rights), **COMMERCIAL-NO-HATE**, **PERSONAL**, **PERSONAL-NO-HATE**. Irrevocable except hate-speech termination; rights pass to each new holder; texts on Arweave `ar://zmc1WTspIhFyVY82bwfAIcIExLFH5lUcHHUN0wXg4W8/<0–5>`, themselves CC0 | a16z-contracts README and `CantBeEvil.sol`; a16zcrypto.com **[src]** |
| QubicBay collections | n/a | A per-collection **label** picked at creation and stored off chain: EXCLUSIVE, NON_EXCLUSIVE, COMMERCIAL or PERSONAL (described as "exclusive / non-exclusive worldwide perpetual license to use, reproduce, display, and distribute", "Commercial Rights", "Personal Use Only"). Current use: 13 NON_EXCLUSIVE, 2 each of EXCLUSIVE, COMMERCIAL and PERSONAL. No full licence text found. The names resemble a16z's variants, but no link to them was found | bundle strings; `/v1/collections` **[live]** |

### 7.5 Options for QDOJO

**Code** (AUD-028):
- **Apache-2.0 or MIT** for the repository. Apache adds a patent grant; MIT matches Core's embedded third-party code.
- Consider **MIT or 0BSD for the example planners**, so builders can copy them freely.
- QDOJO.h: MIT, or MIT plus Anti-Military, as in §7.3.

**Art.** The renderer and the frozen token art are separate questions:
- `apps/web/avatars.js` is deterministic. If it is MIT-licensed, anyone may run it and render any identity's robot. Rights in the *frozen token art* then rest on the selection and the published set, not on scarcity of the generator.
- Decide deliberately between two paths:
  - (i) an open renderer, with the art under a public licence and value coming from the game (the Nouns/CC0 model);
  - (ii) the renderer under a non-commercial or source-available licence (e.g. CC BY-NC 4.0 for its outputs, or PolyForm Noncommercial for its code), plus a holder licence for the frozen art.
- **Legal question:** how far copyright protects algorithmically generated output of human-written code.

**Holder rights** (AUD-010 R7). The candidates:
- **CBE COMMERCIAL-NO-HATE:** a non-exclusive commercial licence to the holder's own fighter image. The creator keeps rights; the licence passes with the token; it is revocable for hate speech.
- **CBE PERSONAL-NO-HATE:** display only. This is the conservative option for launch.
- **CC0:** the maximum spread, with no exclusivity to sell.

In all three cases:
- exclude the **QDOJO name and logo** (trademark);
- state that the token carries game rights (R2, R3) but **no revenue or return promise**;
- publish the text at a permanent URI (Arweave or IPFS) and reference it in the metadata (`license` / `license_uri`) and in the anchored manifest;
- if QBAY is used, set the matching QubicBay label (COMMERCIAL or PERSONAL).

**Suggested default for the owner's legal review:**
- repository code Apache-2.0 (or MIT);
- QDOJO.h MIT, or MIT plus Anti-Military;
- the renderer under the same licence as the site;
- frozen token art under **CBE COMMERCIAL-NO-HATE** for holders, with house trademarks excluded.

---

## Sources

**qubic/core** at `e3ef766`, with per-file last commits as in the header:
- https://github.com/qubic/core/blob/main/src/contracts/Qbay.h
- https://github.com/qubic/core/blob/main/src/contracts/Qx.h
- https://github.com/qubic/core/blob/main/src/contracts/QTREAT.h
- https://github.com/qubic/core/blob/main/src/contract_core/contract_def.h
- https://github.com/qubic/core/blob/main/src/qpi/impl/qpi_assets_impl.h
- https://github.com/qubic/core/blob/main/src/assets/assets.h
- https://github.com/qubic/core/blob/main/src/network_messages/common_def.h
- https://github.com/qubic/core/blob/main/src/public_settings.h
- https://github.com/qubic/core/blob/main/src/contracts/README.md
- https://github.com/qubic/core/blob/main/doc/contracts.md
- https://github.com/qubic/core/blob/main/doc/execution_fees.md
- https://github.com/qubic/core/blob/main/doc/contributing.md
- https://github.com/qubic/core/blob/main/LICENSE.md
- https://github.com/qubic/core/blob/main/LICENSE-MIT.md
- https://github.com/qubic/core/blob/main/README.md

**qubic/proposal:**
- https://github.com/qubic/proposal/blob/main/SmartContracts/2025-03-11-Qbay.md
- https://github.com/qubic/proposal/blob/main/SmartContracts/2026-06-18-Qbay-Upgrade.md
- https://github.com/qubic/proposal/blob/main/SmartContracts/2026-09-18-qtreat_sc_proposal.md

**Live, 2026-09-30:**
- `https://rpc.qubic.org/v1/tick-info`
- `https://rpc.qubic.org/v1/querySmartContract`: QX function 1; QBAY functions 3 and 7 (NFT 5795)
- `https://testnet-rpc.qubic.org` (522)
- `https://testnet.explorer.qubic.org/` (200)
- `https://api.qubicbay.io/v1/collections`
- `https://api.qubicbay.io/v1/nfts`
- `https://qubicbay.io/assets/index-6fc064c1.js`
- `https://gateway.pinata.cloud/ipfs/bafkreiehy5idpkf2qtqk2u52ufvq265t2vcvxsuxejekt6xoacspacg4hq`

**Qubic docs and blog:**
- https://docs.qubic.org/developers/testnet-resources/
- https://docs.qubic.org/developers/dev-kit/
- https://qubic.org/blog-detail/qubicbay-your-gateway-to-nfts-on-qubic (2025-10-13)
- https://qubic.org/blog-detail/qubicbay-part-1-qubicbay-is-bringing-nfts-to-qubic (2025-03-19)
- https://qubic.org/ecosystem/qubicbay

**Wallets and explorer (GitHub API):**
- `qubic/wallet-app` `lib/l10n/app_en.arb`
- `qubic/explorer-frontend` `CHANGELOG.md` and `public/locales/en/network-page.json`
- https://github.com/qubic/qubic-mm-snap
- https://github.com/ardata-tech/qubic-wallet

**QX UIs [2nd]:**
- https://qx.qubic.org/
- https://qubic.org/ecosystem/qubictrade
- https://www.qxboard.com/
- https://github.com/QubicSwap/QubicSwap-DEX

**Game:**
- https://biteonqubic.com/nft/ocean-elements/

**Licensing:**
- https://github.com/a16z/a16z-contracts (README, `contracts/licenses/CantBeEvil.sol`)
- https://a16zcrypto.com/posts/article/introducing-nft-licenses/
- https://www.nouns101.wtf/glossary/cc0
- https://medium.com/dapperlabs/nft-license-2-0-why-a-nft-can-do-what-mickey-mouse-never-could-27673d5f29aa
- https://www.nftlicense.org/
- GitHub API licence fields for `nounsDAO/nouns-monorepo` and `darkforest-eth/darkforest-v0.6`
