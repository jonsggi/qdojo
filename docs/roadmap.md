# Roadmap

## Phase zero, off chain — COMPLETE (2026-09-16)

Built and run: 30 live rounds across an 18-fighter cohort, 149 tests.

- [x] spec, wire protocol, lore, developer API (docs/api.md), modelling notes (docs/model.md)
- [x] pure core: hashing, payloads, round evaluation, settlement
- [x] chain layer: fake for tests, qubic-cli + indexer for real, indexer-lag safe
- [x] house CLI: lobby / publish / collect / settle / void / export / metrics / model / distribute-shareholders
- [x] bot CLI: init (seed + node discovery), bow, run with any solver, stats, shares, dividend, strategy hook
- [x] spectator page: lobby table, rounds, results, void, fighter profiles, eight halls of fame, hash verify
- [x] first live round (2026-09-15) and a full sparring run (68 rounds)
- [x] economics: stake-matched adaptive seed, lobby quorum, belts, bonds, podium, three-way rake
- [x] mathematical model calibrated against the live cohort; gate + rake + NPC findings (docs/model.md)
- [x] self-evolving tool-making fighters, LLM fighters on cheap models, house-funded NPCs

Deferred to phase one (the contract): pure-Python signing to drop the
qubic-cli dependency for bots; the sensei seat and the gate choice; belt
seasons; on-contract bond custody and shareholder claims. The economic
findings above are the brief for the contract's parameters.

## Phase one, the contract
- seats, auctions, inactivity eviction, NPC seats acting at tick boundaries
- commit and reveal inside the contract, pot and rake in state
- IPO of 676 shares, fees to shareholders
- proposal through GQMPROP

## Phase two
- belts as on-chain rank, avatars as Qbay NFTs
- community riddles with an author stake and cut
- parimutuel spectator pools (Quottery's model), after legal review
- oracle-fed riddles once a second oracle interface exists
