# Audit findings and issue backlog

> Combat pivot, 2026-09-21: these findings remain evidence about the legacy
> implementation. The pivot does not close them. Review reusable transport,
> custody, verification, bot admission and asset concerns against the
> [new spec](../docs/spec.md); explicitly resolve or retire each finding
> with evidence during [migration](../docs/pivot-plan.md).

Reviewed **2026-09-16** against commit
`833d2200cff9a05a096666b81783522d3c328f85` (line references refer to that code).

These are actionable issues from a **targeted follow-up review**, not a complete
project/security audit, penetration test, legal opinion, or certification. No
live transactions were sent, no private keystores were accessed, and no historic
loss or cheating is alleged. `docs/PHASE-ZERO.md` says the operator-owned sparring
cohort is stopped; financial priorities below apply before reopening or accepting
outside funds.

## Tracker status

No Git remote is configured in this checkout. Issues are therefore stored locally
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
