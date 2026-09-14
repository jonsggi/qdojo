# Roadmap

## Phase zero, off chain, now
- [x] spec, wire protocol, lore
- [x] pure core: hashing, payloads, round evaluation, settlement
- [x] chain layer: fake for tests, qubic-cli + indexer for real
- [x] house CLI: publish, collect, settle (plan / apply), export
- [x] bot CLI: bow, run against a board with any solver
- [x] spectator page: every round from the beginning
- [ ] first live round on a dedicated house identity
- [ ] pure-Python signing (drop the qubic-cli dependency for bots)
- [ ] secret scanner and pre-commit guard

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
