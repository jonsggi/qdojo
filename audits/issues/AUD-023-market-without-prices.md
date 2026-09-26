# AUD-023 — The simulated market has no prices

- **Status:** Open
- **Priority:** P2 — NFT readiness
- **Type:** Market simulation
- **Evidence:** A sale transfers the fighter to a new collector identity and no price is paid
- **Scope:** `combat/live.py` market, NFT simulation

## Finding

Nothing about demand or valuation can be learned from the current market ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.4).

## Acceptance criteria

- [ ] Simulate priced listings and sales, or remove the market from the demo until it models something.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
