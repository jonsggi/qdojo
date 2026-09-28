# AUD-007 — Align the live pot display with house-fighter seed exclusions

- **Status:** **Retired (riddle code removed 2026-09-28, see tag riddle-v0-final)**
- **Priority:** P1 — correct advertised money before reopening rounds
- **Type:** Frontend/backend accounting mismatch
- **Evidence:** Frontend calculation reproduced; compared with the pure evaluator's matching formula
- **Scope:** `apps/web/app.js:300–319`, `renderFight`; `packages/qdojo/src/qdojo/round.py:294–297`; `packages/qdojo/src/qdojo/house.py:608–624`

> **Retired 2026-09-28.** The owner retired the riddle game (its bonds and pool are the owner's; no closeout obligation remains) and its code was removed. The riddle arcade (`apps/web/app.js`) and its live pot were removed on 2026-09-27; the evaluator went with the riddle code. The code, and the probe that reproduced this finding (`audits/probes/`), live at git tag `riddle-v0-final`; line references below refer to that code.

## Finding

The evaluator matches only counted stakes from identities outside
`spec.house_fighters`. The browser's `livePot()` matches **all** counted stakes,
and the public round export does not supply the affiliation data needed to apply
the exclusion. Even passing a `house_fighters` field directly to the browser
helper currently has no effect.

Settled rounds use `settlement.pot`; this finding concerns the pre-settlement pot
and seed estimates, not evidence that settled payout arithmetic is wrong.

## Reproduction

Run `node audits/probes/browser_findings.cjs`.
Use one pending 1,000-QU stake from a house fighter, a 5,000-QU cap, 1:1 matching
and zero carry. The browser reports 2,000 QU. Under the evaluator's rule, eligible
matched stakes are zero, so the pot should be 1,000 QU.

## Acceptance criteria

- [ ] Export authoritative live pot/seed components or sufficient versioned eligibility data to recompute them correctly.
- [ ] Distinguish total counted stakes, match-eligible stakes, matched seed, fixed seed and carry in the calculation.
- [ ] Missing matching data is marked unavailable/estimated instead of silently treating all stakes as eligible.
- [ ] Share fixtures between Python and browser tests for house-only, mixed, independent-only, capped, carry, fixed-seed and void cases.
- [ ] Make lobby, fight and open-results money displays consistent; preserve settled document values.
- [ ] Document the exported fields and the snapshot/tick to which the live numbers apply.

**Related:** [AUD-006](AUD-006-house-fighter-disclosure.md). Publishing affiliation alone does not fix the calculation without a browser change.
