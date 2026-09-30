# Licensing proposal

> **Purpose:** a recommendation for how QDOJO's code, contract, art and NFTs are licensed. \
> **Audience:** the owner; a lawyer reviewing it. \
> **Status:** proposal (AUD-028). Nothing here is in force until the owner decides and a LICENSE file lands. Not legal advice. \
> **Last reviewed:** 2026-09-30

Facts come from [the Qubic ecosystem research](../research/qubic-nft-ecosystem-2026-09-30.md) §7.

## Recommendation in one table

| Part | Licence | Why |
|---|---|---|
| Repository code: engine, bot SDK, CLI, read API, site, examples, docs | **Apache-2.0** | Builders must be able to reuse the planner interface and examples without asking. Apache adds a patent grant and says outright that it grants no trademark rights |
| The Qubic contract `contracts/qubic/QDOJO.h` | **MIT** | To run on Qubic it must be merged into qubic/core, whose files ship under the Anti-Military License (MIT terms plus a ban on military use). MIT drops into that without friction; Apache-2.0's extra terms would be awkward inside it |
| Fighter art: the generator (`apps/web/avatars.js`, `anim.js`) and every rendered or frozen fighter image | **Separate art licence** (below), not Apache | The art is the NFT. Under Apache anyone could render any fighter and sell prints or a copy collection |
| NFT holder rights | **a16z "Can't Be Evil" COMMERCIAL-NO-HATE** for the fighter you own | A known, audited NFT licence. Holders may use their own fighter commercially and keep their rights after a sale is recorded; hate speech is excluded |
| Name and logo "QDOJO" | **Trademark, not licensed** | Forks may use the code, not the name. Apache already excludes trademarks |
| Contributions | **DCO sign-off** (`Signed-off-by`), no CLA | Lightweight and common. Keeps the option to relicense your own code, not other people's |

## The art licence in practice

- **Everyone:** may view, share and display fighter art non-commercially with credit (CC BY-NC 4.0 terms), including fan art and videos.
- **The holder of a fighter's NFT:** gets COMMERCIAL-NO-HATE rights to that fighter for as long as they hold it.
- **The generator source:** stays public for transparency and verification (`nft verify` must stay reproducible by anyone). It is licensed for viewing and verifying QDOJO fighters, not for making another collection. That makes it source-available, not open source, and the README must say so plainly.

Alternative, if you want the art to spread instead of being scarce: CC0 for all art, as Nouns does. Value then comes only from on-chain ownership and each fighter's fight record, and the licence question disappears. It fits a game whose art is a public function of the fighter id, but it gives up licensing revenue and control over look-alike collections.

## Why not a copyleft or source-available licence for the code

- **AGPL-3.0** would force a forked arena to publish its changes. It is the strongest protection against a closed competing arena, but it scares off some builders and wallet integrators.
- **BSL / source-available** would block competing arenas outright for a few years. It is not open source, and it conflicts with the pitch "the rules and the replays are public, verify everything yourself".
- **What protects QDOJO is not its code.** It is the live arena, the fighters and their records, the NFT collection, the brand and the community. The contract source must be public anyway to enter qubic/core. So a permissive licence costs little and buys adoption.

## Decisions for the owner

1. The copyright holder named in the files: a person or a company.
2. Apache-2.0 for code, and MIT for `QDOJO.h`: accept, or pick AGPL-3.0 for the arena and read API.
3. Art: the scarce model above, or CC0.
4. A trademark search for "QDOJO", and whether to register it.
5. A lawyer's review of the art licence and the holder terms before any mint. The Anti-Military License's "melee weapons" wording should be read with a robot-fighting game in mind; it is almost certainly fine, but have it checked.

Once you have decided, the implementation is:
- a root `LICENSE` (Apache-2.0) and a `NOTICE` file;
- `contracts/qubic/LICENSE` (MIT);
- `apps/web/ART-LICENSE.md`, with SPDX headers in the source files;
- a licence section in the README;
- the licence recorded in the frozen NFT metadata.
