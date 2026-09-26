# AUD-023 — The simulated market has no prices

- **Status:** Fixed in `65ac7b8` (not yet deployed)
- **Priority:** P2 — NFT readiness
- **Type:** Market simulation
- **Evidence:** A sale transfers the fighter to a new collector identity and no price is paid
- **Scope:** `combat/live.py` market, NFT simulation

## Finding

Nothing about demand or valuation can be learned from the current market ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.4).

## Acceptance criteria

- [x] Simulate priced listings and sales, or remove the market from the demo until it models something. `live.Market`: owners list non-founding fighters with asks above a public value (rating, record, experience), asks decay, simulated collectors bid around the value; a sale pays the ask, 250 bps to the house, completing when the fighter is next idle. Payments are journalled (`xfer`) and replay. `market.json` publishes listings, the last 50 sales and price statistics.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
