# Audit findings and issue backlog

> **Purpose:** findings from the 2026-09-16 targeted review of the riddle-era code, and how to reproduce them. \
> **Audience:** the owner; anyone touching money paths, custody or NFTs. \
> **Status:** reference. All ten findings are **open**. They describe the legacy riddle implementation; the combat pivot does not close them. Each must be resolved or retired with evidence before paid combat or an NFT release ([legacy-closeout.md](../docs/legacy-closeout.md), stage P8 of the [roadmap](../docs/roadmap.md)). \
> **Last reviewed:** 2026-09-26: the combat review (AUD-011 to AUD-028) was added below.

Several concerns carry over to combat and should be reviewed against the
[combat spec](../docs/spec.md): verification scope (AUD-008, now reflected in
the site's per-check badges), unattended bot spending (AUD-005, compare the
combat bot's fail-closed budget), and NFT art, allocation, ownership and rights
(AUD-009, AUD-010), which apply directly to fighter NFTs.

Reviewed **2026-09-16** against commit
`833d2200cff9a05a096666b81783522d3c328f85` (line references refer to that code).

These are actionable issues from a **targeted follow-up review**, not a complete
project/security audit, penetration test, legal opinion, or certification. No
live transactions were sent, no private keystores were accessed, and no historic
loss or cheating is alleged. `docs/PHASE-ZERO.md` (now
[archived](../docs/archive/riddle-v0/docs/PHASE-ZERO.md)) says the operator-owned sparring
cohort is stopped; financial priorities below apply before reopening or accepting
outside funds.

## Tracker status

At review time no Git remote was configured (one exists now). Issues are stored locally
in [`issues/`](issues/), with stable `AUD-xxx` IDs. **No hosted issues have been
created.** Each Markdown file can be used as the body of a tracker issue after the
owner/repository is specified. Existing concurrent README/protocol edits were not
changed by this review.

## Issues

All issues are **Open**.

| ID | Priority / gate | Issue | Evidence |
|---|---|---|---|
| [AUD-001](issues/AUD-001-ambiguous-payout-submission.md) | P0 / money restart | Persist payout submission identity before broadcast | Fake-chain duplicate payment reproduced |
| [AUD-002](issues/AUD-002-atomic-settlement-state.md) | P0 / money restart | Make settlement closeout atomic and recoverable | Fake-chain carry inconsistency reproduced |
| [AUD-003](issues/AUD-003-confirm-settle-anchor.md) | P1 / public operation | Confirm SETTLE inclusion before terminal status | Dropped fake SETTLE reproduced |
| [AUD-004](issues/AUD-004-single-writer-state.md) | P1 / unattended operation | Enforce single-writer ownership of state | Code-reviewed concurrency risk; not race-tested |
| [AUD-005](issues/AUD-005-fail-closed-strategies.md) | P1 / unattended bots | Fail closed on crashed/invalid entry strategies | Decision reproduced locally; current contract is fail-open |
| [AUD-006](issues/AUD-006-house-fighter-disclosure.md) | P1 / outside stakes | Publish affiliations and resolve author-participation rules | Code/docs policy conflict; not evidence of cheating |
| [AUD-007](issues/AUD-007-live-pot-matching.md) | P1 / advertised money | Match live pot calculations to house-fighter exclusions | Browser helper mismatch reproduced |
| [AUD-008](issues/AUD-008-verification-scope.md) | P1 / public trust | Separate hash consistency from independent verification | Replacement hash and empty-check success reproduced |
| [AUD-009](issues/AUD-009-freeze-nft-art-and-allocation.md) | P1 / NFT release | Freeze art/traits and define allocation/duplicate policy | Documented preview limitations; no mint exists here |
| [AUD-010](issues/AUD-010-nft-ownership-and-rights.md) | P1 / NFT release | Define ownership, identity binding and artwork rights | Unresolved product/release decisions |

P0 means address before resuming money-moving operation. P1 means resolve before
the stated launch/use gate. Priorities are risk-based recommendations, not CVSS
ratings or assertions about a currently running service.

## Suggested order

1. Design transaction intents and durable accounting together: AUD-001–004.
2. Fix unattended bot spending policy: AUD-005.
3. Establish public participation policy and accurate money/evidence displays:
   AUD-006–008.
4. Resolve collection integrity and ownership/licensing before any NFT release:
   AUD-009–010. Preview artwork can remain available meanwhile.

Changes must preserve the existing arcade visual design; this backlog does not
request another styling overhaul. It also does not authorize production payments,
state rewrites, a mint, or a sale.

## Safe reproductions

From the repository root:

```sh
uv run python audits/probes/financial_findings.py
node audits/probes/browser_findings.cjs
```

The Python probe uses `FakeChain` and temporary directories. The JavaScript probe
loads frontend helpers in an isolated Node VM without booting the app or making
network requests, and copies public fixture data before changing it.

Observed on the reviewed code:

- AUD-001: one 1,000-QU ledger liability credits a fake recipient twice after a
  submission loses its receipt.
- AUD-002: a settlement records 1,000 QU carry while aggregate carry remains zero
  after the closeout state write fails and the House is restarted.
- AUD-003: dropping SETTLE does not prevent terminal status or trigger repair.
- AUD-005: an entry strategy that exits 1 returns an allow-entry decision.
- AUD-007: a house-only 1,000-QU stake displays a 2,000-QU live pot under 1:1
  matching; the evaluator's exclusion requires 1,000 QU.
- AUD-008: modifying the pot and its same-source hash still passes the strong
  browser verification claim; an empty helper check set also reports success.

**These probes assert current defective behavior.** Once fixed, their assertions
should fail; replace them with prevention-oriented regression tests. They are not
part of the normal green test suite and must not be used to preserve the bugs.

## Review boundaries

The source check covered the referenced house, bot, chain adapter, round evaluator,
web verification/money helpers, tests, avatar implementation and related docs.
It did not exhaustively audit the indexer/parser, signing implementation, dependency
supply chain, deployment, node infrastructure, all protocol boundaries, economics,
or proposed contracts. Additional findings may exist. A complete project audit
remains separate work.

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
| [AUD-028](issues/AUD-028-licence.md) | Open | P1 / open-source release | The repository has no licence |

Suggested order for the open items:

1. Keep the fixes honest: AUD-025 (tests that would have caught AUD-011).
2. Foundations for outside players: AUD-026 (read model), AUD-027 (entry
   path), AUD-028 (licence).
3. Before any paid play: AUD-018 and AUD-019 (economics), re-measured after
   the 2026-09-25 bot fixes.
4. Game quality: AUD-020, AUD-021, AUD-022, then AUD-023 and AUD-024.
