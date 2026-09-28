# AUD-010 — Define NFT ownership, fighter identity binding and artwork rights

- **Status:** Mitigated in `f8a734e`: game rights proposed and enforced in the simulation ([nft.md](../../docs/nft.md) §2, R1–R6); licence, recovery and legal review still open
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

- [ ] Define exactly what ownership grants: collectible ownership, avatar display/use, commercial licence, and any exclusions. Game rights proposed (R2: the token is the fighter; R3: winnings to the owner); display and commercial licence open (R7).
- [x] Specify whether fighters can bind/unbind a token, whose signatures authorize that binding, and what happens on token transfer. R1/R2/R4: minted at registration, bound by the asset owner's RegisterFighter, transfer only while idle, new owner re-registers (auth_version + 1).
- [x] Keep private signing seeds out of NFT metadata and transfers; selling a collectible must not implicitly transfer control of a wallet or its money. R2; metadata holds art, traits, bio and hashes only.
- [x] Decide whether rank/history belongs to the fighter identity or follows a token, and make UI/API behavior match that decision. It belongs to the fighter, which the token is; titles are not separately transferable (R2). Site and API show it on the fighter.
- [ ] Specify recovery, disputed bindings and update authority for any dynamic metadata.
- [ ] Obtain an appropriate rights/licensing and branding review; publish the licence and transfer terms before a sale. Original authored art is not, by itself, legal clearance.
- [x] Test unauthorized bindings, replayed authorizations, transfer/unbinding behavior and metadata/rights discoverability if those features are implemented. `test_nft.py` (non-owner orders, locked transfers, re-registration, custody, replay divergence) and `test_scenarios.py`/`test_chainsim.py` (QX transfers mid-contest pay the snapshotted owner).

**Related:** [AUD-009](AUD-009-freeze-nft-art-and-allocation.md). This issue requests explicit policy and implementation tests, not a legal conclusion or a promise of financial returns.
