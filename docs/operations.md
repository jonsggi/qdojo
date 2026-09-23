# Operating combat qdojo

Status: planned combat operations. Current riddle deployment/commands are
documented in [the historical runbook](archive/riddle-v0/docs/operations.md).
Do not run legacy house settlement against a combat state directory.

## 1. Runtime responsibilities

| Component | Authority |
|---|---|
| Qubic combat contract | Accepted actions, rules, deadlines, outcomes, escrow/credits, ratings and locks |
| Owner bot scheduler | Spending decisions, private plans/salts, authorized submissions |
| NPC service | Disclosed practice/exhibition policies; same limited observation as player |
| Indexer/exporter | Confirmed public copies and archival availability; no adjudication |
| Website/replay | Presentation and independent checks; no consensus authority |
| Operator monitoring | Reserve/capacity/availability and alerting; cannot choose winners |

Keep independent network/contract namespaces. Manifest mismatch fails closed.
Display legacy and combat activity distinctly; a static riddle snapshot is not
live combat data.

## 2. Before enabling paid admissions

Complete the acceptance report, pinned Core/ABI vectors, balance/cost evidence,
registry/rights/ownership tests, audit dispositions, custody reconciliation,
release manifest, public timing/fees and incident rehearsal. Confirm all balances
against live state, not stored display numbers. Configure reserve alerts with
capacity for peak settlement and failures.

Production values are explicit; no developer fixture implicitly becomes a
production fee or recipient. Publishing/minting/funding/deploying remains a
separately authorized release action.

## 3. During operation

Monitor execution reserve, service-generation changes, queue capacity/age,
active fight capacity, commit/reveal inclusion delay, protocol faults, nonce
conflicts, exporter lag, replay availability, withdrawal backlog and liabilities.
Break down population/results by independent fighters, known affiliation and NPC.

At every accounting checkpoint compare contract balance with liabilities and
record excluded execution-reserve capital. Don't report credited winnings as
withdrawn money. Never re-send a payout just because an indexer lacks a receipt.

Store private salts/plans before commit. Protect seed/config files with existing
platform-specific protections; no keys in argv, logs, exports or repositories.
Planner subprocesses do not receive signing secrets.

## 4. Incidents

- **Bot/model failure:** use configured fallback before commitment if possible;
  after commitment reveal the exact persisted plan. Stop future spending.
- **Indexer/site failure:** read confirmed contract state; restore exports.
  It does not pause fights or excuse a timeout.
- **Chain produces no ticks:** tick deadlines remain unchanged.
- **Contract-service gap/reserve exhaustion:** protocol generation changes;
  affected unfinished objects void/abort with defined refunds. Restore reserve
  using authorized house capital; do not take player escrow.
- **Bad release/configuration:** stop NEW admissions. Preserve accepted profiles
  and finalized credits. A maintenance flag cannot rewrite winners.
- **Evidence unavailable:** show unavailable and repair archive; never substitute
  "hash matched" for independent verification.
- **Withdrawal transfer failure:** preserve/restore credit according to tested
  platform semantics; retry idempotently after identifying the failure.

Protocol owns the exact service-gap rule. Do not invent an off-chain
"infrastructure failure" classification that selectively cancels losses.

## 5. Capacity and cups

Reserve event capacity before check-in; apply the fixed whole-level postponement
rule if necessary. New queue admissions cannot consume already reserved event
capacity. Expired/invalidated offers release money and locks once.
Full capacity is an admission error, never a reason to delete credits.

Archive accepted inputs and replays redundantly before old event-ring entries
roll over. Preserve current root/sequence evidence so exports can be checked.
Historical availability has its own uptime/retention report.

## 6. Legacy closeout

Inventory every old open round, payout intent, bond, carry amount and owner
before migration. Keep the original versioned records and balances until an
explicit closeout plan reconciles them. Don't infer "unreleased externally"
means the operator's historic funds/transactions do not exist.

No riddle rank, solve point, bond progress or historical payout is automatically
converted into a combat rating, season score, power upgrade or combat purse.
State migrations are reviewed, dry-run and reversible before any live action.

## 7. Documentation and publication

The new agent briefing is unsigned until separately published. Preserve the old
signed briefing in the archive; do not retain its provenance marker on changed
text. Public deployment must update help, API examples and frontend data together.
Check native/Windows onboarding against actual shipped combat commands, rather
than rebranding the old ./dojo riddle flow.
