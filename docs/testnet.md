# Moving the arena to Qubic testnet

> **Purpose:** the checklist for moving the public arena from the simulated chain (devnet) to Qubic testnet: what the code supports today, the exact steps, and what is still missing. \
> **Audience:** operators, the contract owner. \
> **Status:** guide. A checklist, not an implementation: several steps need code that does not exist yet (marked **MISSING**). Qubic facts are cited; anything not confirmed is marked **UNCONFIRMED**. \
> **Last verified:** 2026-09-30 (contract section: branch work/contract-c3; Qubic facts from the round-3 NFT research against qubic/core `e3ef766`, v1.305) \
> Earlier: 2026-09-28 (repository state on branch work/golive; Qubic docs and repositories as linked, read 2026-09-28)

The site needs no code change for the move. Every network-dependent word on
it (the DEVNET/TESTNET badge, the footer line, the currency, the FAQ, the
join panel) comes from the arena's own export: `index.json` →
`deployment.kind` (`devnet`, `testnet` or `mainnet`). A testnet arena that
publishes `"kind": "testnet"` gets the TESTNET badge and "testnet QU"
everywhere; `mainnet` removes the badge and reads plain "QU". Unknown or
missing kinds read as devnet, so the site never claims a real network on a
guess (`apps/web/combat/app.js`, `NETWORKS`).

## 1. Where things stand

| Piece | Today | For testnet |
|---|---|---|
| Contract | `contracts/qubic/QDOJO.h`, Core's dialect: candidates 1, 2 and 3 as tables keyed by digest (the compiled manifest names candidate 3 and the demo-c3 economics), fighters bound to a real asset (issuer, name) by AdminBindAsset. Passes `qubic/contract-verify`, compiles in core-lite, replays every parity journal and the live arena's journal in Core's harness ([contracts/qubic/README.md](../contracts/qubic/README.md)) | Never ran on a ticking node. Release manifest, contract index, the NFT procedures and the fee reserve still open (§3.1) |
| Qubic client | `packages/qdojo/src/qdojo/qubic/`: K12, FourQ, SchnorrQ, identities, transactions, the node TCP protocol (`node.py`: tick info, entity, broadcast, tick transactions, contract functions, owned assets), byte-identical to qubic-cli (`scripts/crosscheck-signer.py`) | Reusable as is |
| Arena runtime | `qdojo combat live` drives the reference contract on `SimChain` (`combat/chainsim.py`): simulated latency, drops, fees and asset registry | **MISSING:** a chain adapter that sends `Dispatch` transactions to a Qubic node and reads confirmed state back (§3.6) |
| Export, read API | Written from the reference contract's state and the devnet journal (`combat/export.py`, `combat/readmodel.py`) | **MISSING:** an exporter and read model fed from confirmed on-chain transactions and contract functions |
| Fighter NFTs | `nft_backend: sim` (`combat/nft.py`, [nft.md](nft.md)); `qbay-mirror` (`combat/nft_qbay.py`, [nft.md](nft.md) §5.4) mirrors ownership read-only from a mainnet QBAY collection and runs today; `qubic` is a stub (`combat/nft_qubic.py`) that builds the real QX transactions and refuses to send | The plan: a mainnet QBAY collection with a testnet arena (§3.7); AdminMirrorOwner (104) in `QDOJO.h` |
| Site | Static nginx image; endpoints from `QDOJO_LIVE_DATA` / `QDOJO_LIVE_API`, public origin from `QDOJO_SITE_URL`; labels from the export | Ready (§3.9) |

## 2. Decisions before starting

1. **Which testnet.** Qubic has a public testnet (RPC
   `https://testnet-rpc.qubic.org`, explorer `https://explorer.qubic.org/`,
   [testnet resources](https://docs.qubic.org/developers/testnet-resources/)),
   but "deploying your contract requires assistance from the Qubic
   developers" through their Discord
   ([testing on testnet](https://docs.qubic.org/developers/smart-contracts/testing/testnet/)).
   The alternative is a self-run single-node testnet with
   [core-lite](https://github.com/qubic/core-lite) (`-DTESTNET=ON`) or the
   [AIO dev kit](https://github.com/qubic/aio-qubic-dev-kit). **UNCONFIRMED:**
   the public testnet RPC did not answer from the ops host on 2026-09-28
   (every request timed out), while mainnet `rpc.qubic.org` did.
2. **Hardware for a self-run testnet.** core-lite's own accounting on this
   build says 12 GB RAM (`TESTNET_LITE_RAM`; the ops host has 7.9 GB and the
   node was OOM-killed, [contracts/qubic/README.md](../contracts/qubic/README.md#local-testnet-core-lite-step-4)).
   core-lite's README gives 16 GB as the minimum for a local testnet; the AIO
   dev kit wants 24 GB or more.
3. **Domain.** Keep `qdojo.jonsggi.com` or give the testnet arena its own
   origin (set `QDOJO_SITE_URL` accordingly).
4. **NFT route.** The plan (2026-10-03): **fighters are a QBAY collection on
   mainnet; the arena runs on testnet** and mirrors their holders through the
   read-only bridge (`nft_backend: qbay-mirror`, [nft.md](nft.md) §5.4).
   Step 1, proving the bridge against an existing mainnet collection, is
   done. The earlier alternatives still stand if the plan changes: issue fighter assets from the QDOJO contract itself
   (`qpi.issueAsset`, contract keeps management rights) or through QX
   (QX-managed; fee **UNCONFIRMED**) ([core contracts doc](https://github.com/qubic/core/blob/main/doc/contracts.md),
   [QX](https://docs.qubic.org/learn/qx/)).
5. **Writes.** Whether outside builders may join on testnet
   (`QDOJO_JOIN_OPEN`, [build-a-bot.md](build-a-bot.md) §8), and with which quotas.

## 3. Checklist

### 3.1 Contract

Done on branch work/contract-c3 (details and outputs in
[contracts/qubic/README.md](../contracts/qubic/README.md)):

- [x] Candidate 3 in the contract. QDOJO.h holds candidates 1, 2 and 3 as
      tables keyed by digest; INITIALIZE takes the table of the manifest's
      digest and admission accepts only that digest. Replayed in Core's
      harness: every committed journal (candidate 1, 2 and 3) and the live
      arena's candidate-3 journal (117,600 ticks, 92,132 calls), each to the
      reference's final event digest.
- [x] The compiled-in manifest names candidate 3 and the live demo-c3
      economics (timing 9/8, tiers 5,000 and 20,000 QU, fee profiles 1 and 2,
      2,400-tick epochs). Its identities are still the synthetic test keys.
- [x] Registration carries the asset: AdminBindAsset (opcode 103) names the
      fighter's issuer and asset name, and ownership is read from that asset
      ([protocol.md](protocol.md) §3). The interim issuer = fighter_id binding
      of opcode 100 stays only for simulated arenas.
- [x] The construction epoch in the local build is the pinned release's epoch,
      232 (`core_harness.py`, `CONSTRUCTION_EPOCH`), so a local TESTNET node
      constructs QDOJO at start.
- [x] Procedure and function IDs are the contract's own ABI and are frozen for
      v1: `Dispatch` is user procedure 1; the queries are functions 1–10
      ([contracts/qubic/README.md](../contracts/qubic/README.md)). What the
      network assigns is the contract **index** (below).

Still open:

- [ ] **Release manifest.** Real admin, house, dev and share identities
      (testnet seeds, §3.3), the testnet `network_id` (§3.5), and timing
      windows recomputed for the measured tick length (§3.2). Replace
      `loadDefaultManifest` with these values before any build that leaves
      this host.
- [ ] **Contract index.** The next free index in `contract_def.h` is 31
      today (qubic/core `e3ef766`). The index fixes the contract identity,
      which becomes the export's `contract_id`. At index 31 or higher QDOJO
      may call QX (1) and QBAY (12); lower-index contracts cannot call it.
- [ ] **Fighter NFT procedures (recommended model, [nft.md](nft.md) §5.3).**
      QDOJO issues each fighter's one-share asset itself (`qpi.issueAsset`,
      issuer = the contract; no QX fee) and keeps management; then binds it
      with the 103 shape (issuer = the contract's identity). Still to write,
      with parity tests against journals carrying `nft` records: the issue
      procedure, the §3 book (asks, bids, escrow, royalty, the contest lock),
      `PRE_ACQUIRE_SHARES` accepting QX returns at fee 0 for QDOJO-issued
      assets only, `PRE_RELEASE_SHARES` refusing pulls, and an owner-invoked
      exit to QX while the fighter is IDLE (QDOJO pays QX's 100 QU). Without
      them a testnet run can bind QX-issued assets through 103, at
      1,000,000,000 QU per issuance even on testnet (one pre-funded seed each).
- [ ] **Execution-fee reserve.** A contract whose reserve reaches 0 skips
      BEGIN_TICK/END_TICK and refuses user procedures. QDOJO dirties its
      1.5 MB state every tick (about 1.4 ms of K12 per tick on this host);
      decide how Dispatch attachments refill the reserve (`qpi.burn`) before
      a long run.
- [ ] Re-run the proof set after any edit: `make qubic-verify`,
      `make qubic-core-test`, `make qubic-core-syntax` (commands in
      [contracts/qubic/README.md](../contracts/qubic/README.md#commands)).
- [ ] Measure on a ticking node: execution fees (README item 3), the per-tick
      state digest (item 4), epoch-boundary tick succession (item 8).

Mainnet inclusion is a different path, and so is a slot on the public
testnet run by the Qubic developers ([core contracts doc](https://github.com/qubic/core/blob/main/doc/contracts.md),
"Development" to "Deployment"; [lifecycle](https://docs.qubic.org/developers/smart-contracts/lifecycle/)):

1. a PR to `qubic/core` `develop` with the `contract_def.h` entry at the next
   free index, passing `contract-verify`, GoogleTest coverage, a core-dev
   review of style and dialect, and a multi-node testnet run;
2. the proposal text with the final source in `qubic/proposal/SmartContracts`;
3. a computor proposal in epoch N with at least 451 votes and more yes than no;
4. epoch N+1: the code ships and a Dutch-auction IPO sells 676 shares; the
   proceeds are burned into QDOJO's execution-fee reserve;
5. epoch N+2: construction. A failed IPO leaves the contract unusable.

Epochs are one week and end on Wednesday at 12:00 UTC; ticks ran at about
0.7 s on mainnet in epoch 232.

### 3.2 Node and network

- [ ] Self-run: build core-lite with QDOJO compiled in
      (`-DTESTNET=ON -DTESTNET_LITE_RAM=ON`, exact command in
      [contracts/qubic/README.md](../contracts/qubic/README.md#local-testnet-core-lite-step-4))
      on a host with enough RAM, and set the tick pace with
      `--ticking-delay <ms>` ([core-lite](https://github.com/qubic/core-lite)).
      Its HTTP API is on port 41841 (`/live/v1`, `/query/v1`). Keep `PATH`
      emptied as in the README so the crash reporter cannot phone home.
- [ ] Public: agree the contract slot and epoch with the Qubic developers,
      then point the adapter at the testnet node or
      `https://testnet-rpc.qubic.org` (**UNCONFIRMED** reachability, see §2).
- [ ] Measure the real tick length. Commit and reveal windows are in ticks
      (demo-c3: 9 and 8 at 1.5 s per tick); a slower chain needs the windows
      recomputed so a planner still gets a few seconds, and the export's
      `deployment.tick_seconds` must carry the measured value.

### 3.3 Identities and seeds

A seed gives the same identity on mainnet, testnet and the devnet: the
derivation has no network input, and a transaction carries no chain id
(`qdojo.qubic.ids`, `qdojo.qubic.tx`; [nft.md](nft.md) §5.4). So a
transaction signed for tick T is valid on any network at tick T. Keep the
identities that sign on testnet free of mainnet funds, or sign only
zero-amount transactions with them.

Never print a seed, never put one on a command line or in a log, and never
reuse a seed that holds mainnet QU.

- [ ] Create testnet-only seeds (55 lowercase letters) for the operator
      (house), the dev and share recipients, and each house bot. Derive the
      public identities with `qdojo.qubic.identity_from_seed` inside a
      process that reads the seed from the environment; only identities are
      written down.
- [ ] Store the seeds in Infisical under a testnet environment, separate from
      anything mainnet, and inject them with `infisical run` as the devnet
      units do today.
- [ ] The house bots' lineup file keeps labels and policies; the seed per bot
      comes from the environment, not from `lineup-arena.json`.

### 3.4 Testnet QU

- [ ] Fund the operator and bot identities from the faucet: a command in
      `#bot-commands` on the Qubic Discord
      ([testnet resources](https://docs.qubic.org/developers/testnet-resources/);
      the exact command is **UNCONFIRMED**). The same page publishes a
      pre-funded shared seed; do not use it for anything that must stay
      yours.
- [ ] On a self-run core-lite testnet every built-in computor seed and any
      custom seed starts with 10B QU ([core-lite](https://github.com/qubic/core-lite)).
- [ ] Size the funding: stake tiers (5,000 / 20,000 on demo-c3), cup entry
      fees, and the contract's execution-fee reserve (unknown until item 3 is
      measured).

### 3.5 Manifest and release fields

The manifest (`/data/combat/v1/manifest.json`) and `index.json` are what the
site and every verifier trust. For testnet:

- [ ] `network_id`: today a placeholder (`d0d0…d0`). Decide the testnet value
      (**decision**: e.g. a hash naming the network and its epoch) and keep it
      stable; the site only shows the read API when the API's `network_id`
      matches the manifest's.
- [ ] `contract_id`: the contract's identity from its index (§3.1).
- [ ] `ruleset_digest`, `semantic_version`: unchanged from the live arena
      (combat-v1-candidate-3, `cf19b7cf…`), the ruleset the contract's
      compiled manifest names.
- [ ] `timing_profiles`, `tiers`, `fee_profiles`, `match_interval_ticks`,
      `ticks_per_epoch`: as deployed in the contract, recomputed for the real
      tick length (§3.2).
- [ ] `index.json` `deployment`: `"kind": "testnet"`, `"currency": "testnet QU"`,
      `"identities": "testnet"`, `"chain": "qubic-testnet"` (a string, so the
      site hides the simulated-chain statistics), `tick_seconds` measured, and
      no simulated-chain `chain` object. Today only `combat/live.py`
      `DEPLOYMENT` writes this block, and it is a devnet by construction.
- [ ] `llms.txt` "Network" section: it is static text; say the arena is on
      testnet there once the export does.

### 3.6 Arena runtime (MISSING)

What exists is the reference contract on `SimChain`. A testnet arena needs:

- [ ] **MISSING:** a chain adapter with the `SimChain` surface the arena and
      bots use (submit, confirm, balances, assets), backed by
      `qubic.node.Node` (`broadcast`, `tick_transactions`, `entity`,
      `contract_function`, `owned_assets`). Every `Dispatch` becomes a signed
      transaction to the contract index with the 512-byte input frame.
- [ ] **MISSING:** an exporter that builds the public export from confirmed
      transactions and contract functions instead of the in-process contract,
      and a read model that follows the chain instead of the devnet journal.
      Until then REPLAY_MATCH is still the best level; COMBAT_VERIFIED needs
      chain inclusion evidence the site can check.
- [ ] **MISSING:** house bots (`qdojo combat bot`) against the adapter, with
      their seeds from the environment (§3.3).
- [ ] A fresh state directory, never the devnet's `~/.qdojo/combat/arena/`,
      and new systemd units (e.g. `qdojo-combat-testnet`, `qdojo-combat-testnet-api`)
      on their own port. Leave the devnet units untouched until the switch.

### 3.7 NFT backend

**The plan: a mainnet QBAY collection with a testnet arena.**

1. [x] **Read-only bridge against an existing collection** (step 1,
   2026-10-03). The client and decoder are `qdojo.qubic.qbay` with
   `qdojo.qubic.rpc`; the backend is `combat/nft_qbay.py`. The demo arena
   mirrored BITE: Ocean Rebels (QBAY collection 17) onto eight fighters, then
   handled a simulated QubicBay sale and an RPC outage
   ([nft.md](nft.md) §5.4). It costs nothing and sends nothing.
2. [ ] **`QDOJO.h` gets AdminMirrorOwner (104)**, re-proved in Core's harness
   with a `mirror.journal`
   ([contracts/qubic/README.md](../contracts/qubic/README.md#follow-up-adminmirrorowner-opcode-104-for-the-qbay-mirror-backend)).
3. [ ] **Our own collection**, prepared with [nft.md](nft.md) §5.5: art
   freeze, bare-CIDv1 IPFS pins, QubicBay's metadata shape, the 1,000-id
   mapping, size and CFB price, royalty ≤ 10% and the COMMERCIAL label. Then
   create and mint it on mainnet from the house identity and pin its ids with
   `qdojo combat qbay pin`.
4. [ ] **The testnet arena** created with `--nft-backend qbay-mirror
   --qbay-config qbay.json`. Its bridge identity is the manifest's admin; it
   needs testnet QU only for the AdminMirrorOwner transactions. That
   identity must never hold mainnet funds: a transaction carries no chain id
   (§3.3).
5. [ ] **Holders register on testnet** with the seed that holds the NFT on
   mainnet (the same identity, [nft.md](nft.md) §5.4), or delegate to an
   operator.

Trust model: the bridge is centralised and testnet-only. On mainnet QDOJO
would read `getInfoOfNFTById` itself (the QTREAT pattern), with no bridge.

The alternatives below stay as written in case the plan changes.

`nft_backend: sim | qubic` is fixed when an arena is created
([nft.md](nft.md) §5). A testnet arena is created with `qubic`; today that
backend is a stub and the live arena refuses to start with it.

- [ ] Pick the realization ([nft.md](nft.md) §5.3, decision 4 in §2).
      Recommended: QDOJO-issued, QDOJO-managed assets with an exit to QX (the
      simulated model; needs the NFT procedures of §3.1 in `QDOJO.h`). The
      fallback is QX assets: issuance costs 1,000,000,000 QU per asset on
      testnet too, and there is no royalty or contest lock. QBAY records are
      not assets and QBAY cannot mint on a fresh testnet (its operator is a
      hard-coded mainnet identity), so do not bind to QBAY.
- [x] The protocol change so registration carries the real (issuer, name):
      AdminBindAsset, opcode 103 ([protocol.md](protocol.md) §3). The live
      arena already registers new fighters with it, naming their simulated
      NFT's issuer and asset name.
- [ ] **MISSING:** signing and sending (`qubic.tx.Transaction.sign`,
      `Node.broadcast`, targeting the current tick + ~10), confirmation
      (`Node.tick_transactions`, then re-read the effect, resend when
      dropped), reads (ownership and possession via `Node.asset_records`, QX
      books via `querySmartContract`, sales via a QX trade-log indexer) and
      live QX fees before any write ([nft.md](nft.md) §5.3, steps 1–6).
- [ ] The market's house owners and collectors are an arena feature, not a
      chain one; decide whether they trade on testnet at all.
- [ ] The site's NFT pages already word themselves from `deployment.kind`:
      on testnet the HOW TO BUY box marks TESTNET as NOW and says a purchase
      is a QX bid from the buyer's own wallet. Check that sentence is true
      before the export says `testnet`.

### 3.8 Data server and read API

- [ ] Start the testnet exporter and `qdojo combat api` (or its successor)
      on the ops host, reachable from the site over the tailnet, e.g.
      `http://100.101.145.63:<port>`.
- [ ] Check `GET /api/v1/status` returns the testnet `network_id` and
      `contract_id`.

### 3.9 Site

- [ ] In Dokploy, set for the site container:
      `QDOJO_LIVE_DATA` and `QDOJO_LIVE_API` (the testnet data server and API),
      `QDOJO_SITE_URL` (the public origin, no trailing slash; share links,
      canonical URL, robots.txt and sitemap.xml are rewritten to it), and
      `QDOJO_JOIN_OPEN` (0 unless §2 decision 5 says otherwise).
- [ ] Refresh the baked fallback export in `apps/web/data/combat/v1/` with a
      testnet snapshot (or remove the devnet copy): when the data server is
      down nginx serves that copy, and a devnet snapshot there would bring the
      DEVNET badge back.
- [ ] Nothing else: the badge, footer line, currency and FAQ follow
      `deployment.kind`.

### 3.10 Before announcing

- [ ] The header shows TESTNET, its tooltip and the footer say testnet QU has
      no monetary value, and the market and economy screens say "testnet QU".
- [ ] A finished fight replays to REPLAY_MATCH in the browser; the ruleset
      digest PASSes on #rules.
- [ ] `node apps/web/tests/e2e/run.cjs` and `make test` pass; the response
      headers include the Content-Security-Policy and no page logs a CSP
      violation.
- [ ] Rollback is one change: point `QDOJO_LIVE_DATA` / `QDOJO_LIVE_API` back
      at the devnet units, which kept running.

## 4. What is missing, in one table

| Gap | Where | Blocks |
|---|---|---|
| Release manifest (real identities, testnet `network_id`, timing for the measured tick), contract index | `contracts/qubic/QDOJO.h` `loadDefaultManifest`, qubic/core registration | Deploying the contract |
| NFT procedures in the contract (issue, book, lock, royalty, QX exit and return) | `contracts/qubic/QDOJO.h`, parity journals with `nft` records | QDOJO-managed fighter NFTs (QX-issued assets can bind through opcode 103 meanwhile) |
| Execution-fee reserve policy | `contracts/qubic/QDOJO.h` | A long run on a ticking node |
| A testnet node with QDOJO (12–16 GB RAM, or a slot on the public testnet via the Qubic developers) | Infrastructure | Everything on chain |
| Chain adapter over `qubic.node.Node` | `packages/qdojo/src/qdojo/combat/` | Arena, bots |
| Exporter and read model from chain | `combat/export.py`, `combat/readmodel.py` | Site data, API |
| Fighter asset issuance and transfers on chain | Contract, `nft_backend: qubic` | Fighter NFTs |
| A testnet `network_id` value | Manifest | Site/API pairing |
| Execution-fee and tick-length measurements | Live node | Timing windows, economics |
