# AUD-010 — Define NFT ownership, fighter identity binding and artwork rights

- **Status:** Open
- **Priority:** P1 — NFT release gate; not a blocker for previewing avatars
- **Type:** Product policy / authorization / legal review
- **Evidence:** Unresolved release decisions identified in `apps/web/AVATARS.md`; not a finding of existing infringement
- **Scope:** `apps/web/AVATARS.md` “Before an NFT release”; `apps/web/avatars.js` public identity-based art API

## Finding

The current UI associates artwork with a Qubic fighter identity. An NFT holder,
a fighting-wallet controller and an artwork licensee are not necessarily the
same person. A transfer policy and explicit artwork rights have not been
implemented by the avatar preview system.

Without a written model, buyers could misunderstand whether a transfer includes
fighter control, earned belt/rank, performance history, display exclusivity,
commercial rights, or none of those. No such promises should be inferred from an
SVG export or from possession of an identity-derived character image.

## Acceptance criteria

- [ ] Define exactly what ownership grants: collectible ownership, avatar display/use, commercial licence, and any exclusions.
- [ ] Specify whether fighters can bind/unbind a token, whose signatures authorize that binding, and what happens on token transfer.
- [ ] Keep private signing seeds out of NFT metadata and transfers; selling a collectible must not implicitly transfer control of a wallet or its money.
- [ ] Decide whether rank/history belongs to the fighter identity or follows a token, and make UI/API behavior match that decision.
- [ ] Specify recovery, disputed bindings and update authority for any dynamic metadata.
- [ ] Obtain an appropriate rights/licensing and branding review; publish the licence and transfer terms before a sale. Original authored art is not, by itself, legal clearance.
- [ ] Test unauthorized bindings, replayed authorizations, transfer/unbinding behavior and metadata/rights discoverability if those features are implemented.

**Related:** [AUD-009](AUD-009-freeze-nft-art-and-allocation.md). This issue requests explicit policy and implementation tests, not a legal conclusion or a promise of financial returns.
