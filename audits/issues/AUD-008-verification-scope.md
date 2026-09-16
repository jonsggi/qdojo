# AUD-008 — Separate local hash consistency from independent round verification

- **Status:** Open
- **Priority:** P1 — correct trust claims before public use
- **Type:** Verification / misleading assurance
- **Evidence:** Local counterexamples reproduced; no live chain audit performed
- **Scope:** `apps/web/app.js:435–483` (`verifyRound`, `runVerify`)

## Finding

The browser recomputes hashes and compares them with hashes provided in the same
house-controlled JSON. It does not independently retrieve authenticated PUBLISH
or SETTLE payloads, prove transaction inclusion, establish completeness of the
observed entries, or recompute payouts. Yet success says “ALL CHECKS PASS · THE
HOUSE DID NOT MOVE THE GOALPOSTS” and the callout says “VERIFIED.”

`res.every(...)` also returns true for an empty result set. Missing required
riddle/answer fields may omit checks rather than explicitly fail completeness.
Explorer links are useful evidence pointers, but are not verification by this
browser routine.

## Reproduction

Run `node audits/probes/browser_findings.cjs`:

1. Copy a local settled round, increment its pot without changing payouts, and
   recompute the JSON's settlement hash. The browser still emits the strong
   success claim; it never checks payout conservation or the on-chain anchor.
2. Call the verifier with a round containing no applicable evidence. It emits
   “ALL CHECKS PASS” even though no checks ran. This is a helper-level case,
   not a claim that every normal results page can reach that state.

## Acceptance criteria

- [ ] Label current success as **local published-data hash consistency**, with explicit exclusions for chain inclusion, completeness and payout correctness.
- [ ] Model passed/failed/missing/not-applicable checks; an empty or incomplete required check set cannot be verified.
- [ ] Define required checks for live, settled and void rounds separately.
- [ ] Add an independent verification path that retrieves/validates the relevant chain payloads and provenance, or keep unsupported guarantees explicitly unverified.
- [ ] Add pure replay/conservation checks before claiming payout correctness, and explain that replay still depends on complete input evidence.
- [ ] Test same-source replacement hashes, missing commitments/salts/hashes, unavailable WebCrypto, failed anchors and tampered payouts.
- [ ] Preserve the existing arcade visual design; this issue needs accurate labels and behavior, not a redesign.

**Related:** [AUD-003](AUD-003-confirm-settle-anchor.md), [AUD-006](AUD-006-house-fighter-disclosure.md).
