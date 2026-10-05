# Audit findings and issue backlog

> **Purpose:** audit findings, their status, and how to reproduce them. \
> **Audience:** the owner; product, game, frontend, protocol and operations contributors. \
> **Status:** reference. Combat findings AUD-011 to AUD-028 and product follow-ups AUD-029 to AUD-041 are below. Of the ten riddle-era findings, AUD-006 remains open, AUD-009 and AUD-010 are mitigated, and seven are retired with the riddle code. \
> **Last reviewed:** 2026-10-03: recorded the 2026-09-30 product review and updated its related findings.

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
| [AUD-021](issues/AUD-021-balance-kick-duck.md) | Mitigated (candidate 3: 11/11 gates; human study in AUD-038) | P2 / strategic depth | Kick dominates; duck and throw are near useless |
| [AUD-022](issues/AUD-022-pacing.md) | Mitigated (profile `demo-c2`, 9/8 ticks; wiring 67f10c1) | P2 / spectator experience | A ranked fight takes twice the target time |
| [AUD-023](issues/AUD-023-market-without-prices.md) | **Fixed** 65ac7b8 | P2 / NFT readiness | The simulated market has no prices |
| [AUD-024](issues/AUD-024-unbounded-growth.md) | **Fixed** 67f10c1 | P2 / operations | index.json and restart time grow without bound |
| [AUD-025](issues/AUD-025-overdue-invariant.md) | **Fixed** 67f10c1 | P1 / regression safety | Tests accepted overdue live fights |
| [AUD-026](issues/AUD-026-read-model-database.md) | Fixed in 7557e2a, cb5a22d (deploy pending) | P1 / product foundation | Full history needs a read model, not static files |
| [AUD-027](issues/AUD-027-outside-builder-entry.md) | Entry implemented; beta enablement and independent journey open | P1 / product | Outside builders cannot enter the arena |
| [AUD-028](issues/AUD-028-licence.md) | Open (proposal ready) | P1 / open-source release | The repository has no licence |

Suggested order recorded with the September 25 review:

1. Keep the fixes honest: AUD-025 (tests that would have caught AUD-011).
2. Foundations for outside players: AUD-026 (read model), AUD-027 (entry
   path), AUD-028 (licence).
3. Before any paid play: AUD-018 and AUD-019 (economics), re-measured after
   the 2026-09-25 bot fixes.
4. Game quality: AUD-020, AUD-021, AUD-022, then AUD-023 and AUD-024.

## Product review 2026-09-30 (issues recorded 2026-10-03)

The [review and coverage map](reports/2026-09-30-product-review.md) distinguish
reproduced defects, design findings and proposed research. Live observations
are dated September 30; relevant code and the starter failures were rechecked
on October 3 at 2eb5ef8b. These issues follow the repository's local Markdown
backlog convention.

| ID | Status | Priority / gate | Issue |
|---|---|---|---|
| [AUD-029](issues/AUD-029-starter-planner-new-moves.md) | **Fixed** d1d5ff5b: ruleset-aware starter, both copies identical and tested | P1 / outside onboarding | Make the starter planner compatible with every supported ruleset |
| [AUD-030](issues/AUD-030-onboarding-ruleset-consistency.md) | **Fixed** d1d5ff5b, 7a0837c3: V3 default, docs aligned, release checklist (operations.md §7) | P1 / outside onboarding | Align onboarding commands and explanations with the arena rules |
| [AUD-031](issues/AUD-031-custom-planner-benchmark.md) | **Fixed** d1d5ff5b: `evaluate --planner`, paired comparisons, fallback accounting | P1 / builder improvement | Benchmark a builder's own planner directly from the CLI |
| [AUD-032](issues/AUD-032-fight-debrief.md) | Fixed (1fbced09); new-player check in AUD-038 | P1 / learning | Turn fight results into an actionable debrief |
| [AUD-033](issues/AUD-033-practice-progress.md) | Fixed (1fbced09); first-win observation in AUD-038 | P2 / repeat play | Give practice a saved record and a clear next challenge |
| [AUD-034](issues/AUD-034-share-completed-practice-fight.md) | Fixed (1fbced09) | P1 / public correctness | Make practice sharing preserve the completed fight |
| [AUD-035](issues/AUD-035-first-session-onboarding.md) | Fixed (1fbced09) for title and practice entry; BUILD A BOT entry status with AUD-027, trial with AUD-039 | P1 / activation | Make the first session lead clearly to playing and building |
| [AUD-036](issues/AUD-036-fight-layout-and-readability.md) | **Mitigated** 11059267: stage first, detail folded, reading face; phone move deck (practice-ux) and viewer study open | P2 / usability | Put fights and controls ahead of banners and technical detail |
| [AUD-037](issues/AUD-037-spoiler-free-replays.md) | **Fixed** 11059267: spoiler-free mode on replays, results, title, arena and fighter lists | P2 / spectating | Offer spoiler-free replay viewing |
| [AUD-038](issues/AUD-038-human-strategy-validation.md) | Open (research) | P1 / rules decisions | Validate strategic learning and replay readability with outside builders |
| [AUD-039](issues/AUD-039-builder-beta-and-commercial-evidence.md) | Open (proposal) | P1 / product validation | Run a small builder beta and separate engagement from simulated economics |
| [AUD-040](issues/AUD-040-frontend-modules.md) | Open | P2 / maintainability | Split the frontend controller into modules with clear ownership |
| [AUD-041](issues/AUD-041-builder-journey-acceptance.md) | **Fixed**: builder-journey acceptance test in `make test`; `make release-check` | P1 / regression protection | Test the published builder journey against the active ruleset |

Outside-entry enablement extends **AUD-027**, rather than creating a duplicate.
Human strategy validation extends AUD-021's measured balance work. Real costs,
player economics and licensing remain with AUD-018, AUD-019 and AUD-028.

Recommended order for this follow-up: repair the starter and rules agreement
(029–030), add custom benchmarking (031) and journey coverage (041), complete
entry and first-session guidance (027, 035), sharing and debriefs (034, 032),
then run the builder cohort and human study (039, 038). Improve progress and
presentation (033, 036–037) from that feedback and split the frontend
incrementally (040).
