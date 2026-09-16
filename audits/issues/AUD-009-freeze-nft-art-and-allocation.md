# AUD-009 — Freeze NFT artwork/traits and define collection allocation before minting

- **Status:** Open
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
- [ ] Export and pin immutable artwork and static metadata per token, with a manifest of token ID, source identity where applicable, renderer version, traits and content hashes.
- [ ] Validate duplicates across the complete release set, including visual duplicates caused by hidden/occluded traits, not only distinct SVG bytes.
- [ ] Ensure later renderer deployments cannot change an existing token's pinned assets.
- [ ] Keep live rank/performance separate from static collectible traits and document any explicitly dynamic metadata fields.
- [ ] Test target marketplace rendering, lossless raster fallback, metadata schemas and durable storage before minting.

**Related:** [AUD-010](AUD-010-nft-ownership-and-rights.md). Neither issue authorizes a mint, sale, wallet operation or legal claim.
