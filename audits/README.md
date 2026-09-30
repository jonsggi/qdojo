# Audit findings and issue backlog

> **Purpose:** audit findings, their status, and how to reproduce them. \
> **Audience:** the owner; anyone touching money paths, custody or NFTs. \
> **Status:** reference. The combat review (AUD-011 to AUD-028) is below. Of the ten riddle-era findings, three stay open (AUD-006, AUD-009, AUD-010) and seven are retired with the riddle code. \
> **Last reviewed:** 2026-09-28: the riddle code was removed and its findings dispositioned.

## Riddle-era review 2026-09-16

A targeted follow-up review of the riddle-era code, against commit
`833d2200cff9a05a096666b81783522d3c328f85` (line references in the issue files
refer to that code). It was not a complete project or security audit.

On 2026-09-28 the owner retired the riddle game: its bonds and pool belong to
the owner, no closeout obligation remains, and the riddle code, its site and
the probes that reproduced these findings (`audits/probes/`) were removed. They
live at git tag `riddle-v0-final`. Findings about that code are **retired**;
those that apply to combat stay open.

| ID | Status | Priority / gate | Issue |
|---|---|---|---|
| [AUD-001](issues/AUD-001-ambiguous-payout-submission.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final) | P0 / money restart | Persist payout submission identity before broadcast |
| [AUD-002](issues/AUD-002-atomic-settlement-state.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final) | P0 / money restart | Make settlement closeout atomic and recoverable |
| [AUD-003](issues/AUD-003-confirm-settle-anchor.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final) | P1 / public operation | Confirm SETTLE inclusion before terminal status |
| [AUD-004](issues/AUD-004-single-writer-state.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final) | P1 / unattended operation | Enforce single-writer ownership of state |
| [AUD-005](issues/AUD-005-fail-closed-strategies.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final); principle carried by AUD-013 | P1 / unattended bots | Fail closed on crashed/invalid entry strategies |
| [AUD-006](issues/AUD-006-house-fighter-disclosure.md) | **Open**, carries over to combat | P1 / outside stakes | Publish affiliations and resolve author-participation rules |
| [AUD-007](issues/AUD-007-live-pot-matching.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final) | P1 / advertised money | Match live pot calculations to house-fighter exclusions |
| [AUD-008](issues/AUD-008-verification-scope.md) | Retired (riddle code removed 2026-09-28, see tag riddle-v0-final); combat shows per-check badges | P1 / public trust | Separate hash consistency from independent verification |
| [AUD-009](issues/AUD-009-freeze-nft-art-and-allocation.md) | **Mitigated** f8a734e: freeze/verify pipeline and duplicate check; allocation and contact sheet open | P1 / NFT release | Freeze art/traits and define allocation/duplicate policy |
| [AUD-010](issues/AUD-010-nft-ownership-and-rights.md) | **Mitigated** f8a734e: rules R1–R6 proposed in docs/nft.md and enforced in the simulation; licence open | P1 / NFT release | Define ownership, identity binding and artwork rights |

P0 means address before resuming money-moving operation. P1 means resolve before
the stated launch/use gate. Priorities are risk-based recommendations, not CVSS
ratings or assertions about a currently running service. Issue files are local
Markdown with stable `AUD-xxx` IDs; no hosted issues were created.

## Combat review 2026-09-25

A second review, of the **combat** game running in the live demo arena
(simulated chain, fake QU), with a product review of the site and repository.
It is a replay-based analysis of 34.8 h of arena play, not a security audit.

- [Simulation audit](reports/2026-09-25-simulation-audit.md): liveness,
  economics, balance, fun, with evidence. Supporting CSVs and scripts are in
  [`reports/2026-09-25-simulation/`](reports/2026-09-25-simulation/).
- [Product review](reports/2026-09-25-product-review.md): what would make
  QDOJO a great product.

Seven findings were fixed and deployed on 2026-09-25; the rest are open.

| ID | Status | Priority / gate | Issue |
|---|---|---|---|
| [AUD-011](issues/AUD-011-exporter-froze-finished-fights.md) | **Fixed** d688257 | P0 / public correctness | The exporter froze finished fights mid-round |
| [AUD-012](issues/AUD-012-spent-power-forfeits.md) | **Fixed** 0918949 | P0 / fair play | LLM bots forfeited by reusing a spent power strike |
| [AUD-013](issues/AUD-013-resend-loops-and-fault-stop.md) | **Fixed** 0918949 | P1 / unattended operation (see AUD-005) | Bots re-sent rejected entries every tick; the fault stop was disabled |
| [AUD-014](issues/AUD-014-live-policies-without-history.md) | **Fixed** 0918949 | P1 / game integrity | History-based policies played blind in the live arena |
| [AUD-015](issues/AUD-015-opponent-scouting-empty.md) | **Fixed** 0918949 | P1 / builder experience | Planners could not scout their opponent |
| [AUD-016](issues/AUD-016-bot-run-planner-forfeit.md) | **Fixed** 66c0951 | P1 / builder onboarding | `qdojo combat bot run --planner` forfeited its first local fight |
| [AUD-017](issues/AUD-017-records-ranked-only.md) | **Fixed** d688257 | P1 / public correctness | Fighter records showed ranked fights only |
| [AUD-018](issues/AUD-018-house-economics.md) | Mitigated (demo) f27a972 | P1 / paid launch gate | House economics do not close |
| [AUD-019](issues/AUD-019-player-ev-and-event-farming.md) | **Mitigated** f27a972 | P1 / fairness / outside stakes | Honest players lose money; cups and duels were farmed |
| [AUD-020](issues/AUD-020-ratings-and-seasons.md) | **Mitigated** f27a972 | P2 / competition quality | Ratings do not converge and season titles are noisy |
| [AUD-021](issues/AUD-021-balance-kick-duck.md) | Mitigated (candidate 2 in code; 10/11 gates) | P2 / strategic depth | Kick dominates; duck and throw are near useless |
| [AUD-022](issues/AUD-022-pacing.md) | Mitigated (profile `demo-c2`, 9/8 ticks; wiring 67f10c1) | P2 / spectator experience | A ranked fight takes twice the target time |
| [AUD-023](issues/AUD-023-market-without-prices.md) | **Fixed** 65ac7b8 | P2 / NFT readiness | The simulated market has no prices |
| [AUD-024](issues/AUD-024-unbounded-growth.md) | **Fixed** 67f10c1 | P2 / operations | index.json and restart time grow without bound |
| [AUD-025](issues/AUD-025-overdue-invariant.md) | **Fixed** 67f10c1 | P1 / regression safety | Tests accepted overdue live fights |
| [AUD-026](issues/AUD-026-read-model-database.md) | Fixed in 7557e2a, cb5a22d (deploy pending) | P1 / product foundation | Full history needs a read model, not static files |
| [AUD-027](issues/AUD-027-outside-builder-entry.md) | Mitigated in 7557e2a, cb5a22d (built, off by default) | P1 / product | Outside builders cannot enter the arena |
| [AUD-028](issues/AUD-028-licence.md) | Open (proposal ready) | P1 / open-source release | The repository has no licence |

Suggested order for the open items:

1. Keep the fixes honest: AUD-025 (tests that would have caught AUD-011).
2. Foundations for outside players: AUD-026 (read model), AUD-027 (entry
   path), AUD-028 (licence).
3. Before any paid play: AUD-018 and AUD-019 (economics), re-measured after
   the 2026-09-25 bot fixes.
4. Game quality: AUD-020, AUD-021, AUD-022, then AUD-023 and AUD-024.
