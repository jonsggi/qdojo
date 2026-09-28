# AUD-009 — Freeze NFT artwork/traits and define collection allocation before minting

- **Status:** Mitigated in `f8a734e` (freeze pipeline, verification, duplicate check); release decisions (contact sheet, supply, allocation, marketplace test) still open
- **Priority:** P1 — NFT release gate; not a blocker for the current preview UI
- **Type:** Collection integrity / release engineering
- **Evidence:** Preview design limitations documented and code-reviewed; no mint implementation exists here
- **Scope:** `apps/web/avatars.js` (`hash`, `traits`, `svg`, `VERSION`); `apps/web/AVATARS.md` “Before an NFT release”; `apps/web/tests/avatars.test.cjs`

## Finding

The current renderer derives appearance from public identity hashes and a finite
set of traits. It is deterministic but neither guaranteed unique nor resistant
to generating identities until a desirable appearance is found. The current
uniqueness test covers only the current public roster.

`version` is an informational string, not immutable content-addressed token
metadata. Version 2 intentionally changed some version-1 preview art. That is
acceptable for a preview, but a mutable website renderer is not sufficient to
preserve previously sold token artwork.

These limitations are already disclosed in `AVATARS.md`. This issue turns that
checklist into a release gate; it does not report an exploit against minted NFTs.

## Acceptance criteria

- [ ] Approve a full collection contact sheet and define supply, duplicate policy, trait distribution and allocation before marketing rarity.
- [ ] If traits are intended to be scarce/random, adopt an allocation mechanism appropriate to that promise; do not equate a grindable identity hash with randomness.
- [x] Export and pin immutable artwork and static metadata per token, with a manifest of token ID, source identity where applicable, renderer version, traits and content hashes. `qdojo combat nft freeze` / `scripts/nft-freeze.cjs`: content-addressed SVG, 16x PNG masters and metadata, `manifest.json` with renderer version and hash and a root hash; the sample set is committed under `apps/web/data/nft/v1/sample/` ([nft.md](../../docs/nft.md) §7). Pinning to durable storage (IPFS) is still to do.
- [x] Validate duplicates across the complete release set, including visual duplicates caused by hidden/occluded traits, not only distinct SVG bytes. The manifest lists tokens whose sprites have identical pixels, whatever their SVG bytes.
- [x] Ensure later renderer deployments cannot change an existing token's pinned assets. Assets are content-addressed; `qdojo combat nft verify` fails when the renderer draws different art or a stored file changes (`test_nft.py`); the token page re-hashes the card in the browser and says whether it matches the frozen master.
- [x] Keep live rank/performance separate from static collectible traits and document any explicitly dynamic metadata fields. nft.md R6: metadata is static, `properties.dynamic` says so; rank, belts and record live only in game data.
- [ ] Test target marketplace rendering, lossless raster fallback, metadata schemas and durable storage before minting.

**Related:** [AUD-010](AUD-010-nft-ownership-and-rights.md). Neither issue authorizes a mint, sale, wallet operation or legal claim.
