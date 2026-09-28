# Moving the arena to Qubic testnet

> **Purpose:** the checklist for moving the public arena from the simulated chain (devnet) to Qubic testnet: what the code supports today, the exact steps, and what is still missing. \
> **Audience:** operators, the contract owner. \
> **Status:** guide. A checklist, not an implementation: several steps need code that does not exist yet (marked **MISSING**). Qubic facts are cited; anything not confirmed is marked **UNCONFIRMED**. \
> **Last verified:** 2026-09-28 (repository state on branch work/golive; Qubic docs and repositories as linked, read 2026-09-28)

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
| Contract | `contracts/qubic/QDOJO.h`, Core's dialect. Passes `qubic/contract-verify`, compiles in core-lite, replays all parity journals in Core's harness ([contracts/qubic/README.md](../contracts/qubic/README.md)) | Never ran on a ticking node. Construction epoch, procedure IDs and asset issuance still open (§3.1) |
| Qubic client | `packages/qdojo/src/qdojo/qubic/`: K12, FourQ, SchnorrQ, identities, transactions, the node TCP protocol (`node.py`: tick info, entity, broadcast, tick transactions, contract functions, owned assets), byte-identical to qubic-cli (`scripts/crosscheck-signer.py`) | Reusable as is |
| Arena runtime | `qdojo combat live` drives the reference contract on `SimChain` (`combat/chainsim.py`): simulated latency, drops, fees and asset registry | **MISSING:** a chain adapter that sends `Dispatch` transactions to a Qubic node and reads confirmed state back (§3.6) |
| Export, read API | Written from the reference contract's state and the devnet journal (`combat/export.py`, `combat/readmodel.py`) | **MISSING:** an exporter and read model fed from confirmed on-chain transactions and contract functions |
| Fighter NFTs | `nft_backend: sim` (`combat/nft.py`, [nft.md](nft.md)); `qubic` is a stub (`combat/nft_qubic.py`) that builds the real QX transactions and refuses to send; the live arena refuses to start with it | Realization choice, sending, confirmation and reads (§3.7) |
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
4. **NFT route.** Issue fighter assets from the QDOJO contract itself
   (`qpi.issueAsset`, contract keeps management rights) or through QX
   (QX-managed; fee **UNCONFIRMED**) ([core contracts doc](https://github.com/qubic/core/blob/main/doc/contracts.md),
   [QX](https://docs.qubic.org/learn/qx/)).
5. **Writes.** Whether outside builders may join on testnet
   (`QDOJO_JOIN_OPEN`, [build-a-bot.md](build-a-bot.md) §8), and with which quotas.

## 3. Checklist

### 3.1 Contract

- [ ] Set QDOJO's construction epoch to the testnet's epoch. It is registered
      with 240; core-lite's testnet starts at `EPOCH 232`, so the node would
      never construct it ([contracts/qubic/README.md](../contracts/qubic/README.md)).
      On a public testnet, take the epoch the Qubic developers assign.
- [ ] Replace the placeholder procedure and function IDs ("What remains",
      item 7) and record the final numbers in [protocol.md](protocol.md) and
      the Python client.
- [ ] Get a contract index: the contract goes into `src/contracts/QDOJO.h`
      and is registered in `src/contract_core/contract_def.h` with the next
      free index ([core contracts doc](https://github.com/qubic/core/blob/main/doc/contracts.md)).
      The contract's identity (from the index) becomes the export's
      `contract_id`.
- [ ] Asset issuance for fighters (item 5): the interim binding is issuer =
      fighter_id, name `QDOJOF`, but nothing issues it yet.
- [ ] Re-run the proof set after these edits: `contract-verify`, the
      core-lite test (`test_qdojo_core.cpp`, all parity journals), and
      `core_harness.py` (commands in [contracts/qubic/README.md](../contracts/qubic/README.md#commands)).
- [ ] Still open and worth measuring on a ticking node: execution-fee cost
      (item 3), the 1.4 ms per-tick state digest (item 4), epoch-boundary
      tick succession (item 8).

Mainnet inclusion is a different path (computor proposal, 451 votes, a
676-share Dutch-auction IPO, construction two epochs later;
[lifecycle](https://docs.qubic.org/developers/smart-contracts/lifecycle/)) and
is out of scope here.

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
      (demo-c2: 9 and 8 at 1.5 s per tick); a slower chain needs the windows
      recomputed so a planner still gets a few seconds, and the export's
      `deployment.tick_seconds` must carry the measured value.

### 3.3 Identities and seeds

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
- [ ] Size the funding: stake tiers (5,000 / 20,000 on demo-c2), cup entry
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
- [ ] `ruleset_digest`, `semantic_version`: unchanged (combat-v1-candidate-2,
      `231607f8…`); the site shows it as RULES V2.
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

`nft_backend: sim | qubic` is fixed when an arena is created
([nft.md](nft.md) §5). A testnet arena is created with `qubic`; today that
backend is a stub and the live arena refuses to start with it.

- [ ] Pick the realization ([nft.md](nft.md) §5.3, decision 4 in §2):
      QX assets (proposed for the testnet run; issuance through QX, free on
      testnet, no royalty or contest lock) or QDOJO-managed assets (the
      simulated model; needs the proposed opcodes 20–27 in
      `nft_qubic.QDOJO_PROCEDURES` implemented in `QDOJO.h`).
- [ ] **MISSING:** the protocol change so AdminRegisterAsset carries the
      real (issuer, name): the interim issuer = fighter_id, name `QDOJOF`
      can never be issued, because nobody holds a fighter_id's key.
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
| Construction epoch, final procedure/function IDs, contract index | `contracts/qubic/QDOJO.h`, qubic/core registration | Deploying the contract |
| A testnet node with QDOJO (12–16 GB RAM, or a slot on the public testnet via the Qubic developers) | Infrastructure | Everything on chain |
| Chain adapter over `qubic.node.Node` | `packages/qdojo/src/qdojo/combat/` | Arena, bots |
| Exporter and read model from chain | `combat/export.py`, `combat/readmodel.py` | Site data, API |
| `QDOJOF` issuance and transfers on chain | Contract, `nft_backend: qubic` | Fighter NFTs |
| A testnet `network_id` value | Manifest | Site/API pairing |
| Execution-fee and tick-length measurements | Live node | Timing windows, economics |
