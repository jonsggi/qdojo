# AUD-027 — Outside builders cannot enter the arena

- **Status:** Implementation mitigated in 7557e2a and cb5a22d; entry policy published (docs/beta.md §3, linked from the site's BUILD A BOT page) and entry availability shown there (7a0837c3). Product milestone open: enabling the beta entry is the owner's call (docs/beta.md §5), then an independent builder's journey. Outside entry is still off on the live arena (rechecked 2026-10-10).
- **Priority:** P1 — product
- **Type:** Product
- **Evidence:** Only operator-run bots fight in the arena; builders can practise only locally
- **Scope:** Arena lineup, registration, bot hosting policy

## Finding

The core loop (build, enter, climb, study) stops after local practice ([product review](../reports/2026-09-25-product-review.md)).

## Acceptance criteria

- [x] A registration path for outside fighters on the simulated chain first.
  A SchnorrQ-signed registration; the arena issues a simulated NFT, grants fake QU and registers the asset; the
  builder signs `REGISTER_FIGHTER` and every later action as Qubic-format transactions (`combat/join.py`,
  `qdojo combat join`, [build-a-bot.md](../../docs/build-a-bot.md) §8). Evidence: `tests/combat/test_join.py`
  (register, sign, fight a combat result to the end; refusals for bad signatures, unregistered keys, admin
  opcodes, oversized attachments, stale ticks, wrong contract, name reuse, caps and rate limits).
- [x] Decide who runs the bot (the builder, or a hosted runner with limits).
  The builder runs it. A hosted runner would execute untrusted code on a two-CPU host; the builder-run path
  needs no code execution on the server, only signature checks, quotas and a bounded inbox.
- [x] Disclosure rules for house and outside fighters (see AUD-006).
  `origin` = `house` / `outside` on every fighter in the export and the API, HOUSE/OUTSIDE badges on the
  fighter page and leaderboard. The wider AUD-006 policy questions stay open there.

## Follow-up: complete the participation loop (2026-10-03)

The [2026-09-30 product review](../reports/2026-09-30-product-review.md)
observed 20 house-run fighters and outside entry disabled. The registration
implementation is delivered; that does not close the user-facing milestone.
The live configuration has not been rechecked when this follow-up was written.
*Rechecked 2026-10-10:* the live read API reports `join_enabled: false` and
`GET /api/v1/join` answers 404 `join_disabled`; the site's BUILD A BOT page
shows ENTRY ON THIS ARENA: CLOSED with the next steps.

- [x] Publish the beta entry policy, participant limits and eligibility for
  events against house bots, with accurate house/outside disclosure.
  *Evidence:* [docs/beta.md](../../docs/beta.md) §3 (who may enter; an eligibility
  table for ranked, duels, cups, seasons and the market against house bots; fair
  play from the house; disclosure) and §4 (limits, as shipped in
  `deploy/systemd/join-limits.beta.json`); every fighter carries HOUSE or OUTSIDE in
  the export, the API and the site. The BUILD A BOT page's entry panel links the
  policy (ENTRY POLICY), checked by the browser suite's `join` step.
- [ ] Configure and enable the intended free beta entry path using the documented
  operator switches; verify limits, useful rejection messages and recovery from
  an interrupted registration on that deployment. *Needs the owner:* opening
  entry is an operator decision; the switches and the verification script are in
  docs/beta.md §5. The registration path itself is exercised end to end on a
  local arena by `tests/combat/test_builder_journey.py` (AUD-041).
- [ ] Have an independent builder follow the public instructions, register a
  fighter, complete a combat fight and open its verified replay.
- [x] Show the deployment's entry availability on the builder page, including
  a useful next step when registration is closed. *Evidence:* 7a0837c3: the BUILD
  A BOT page's ENTRY ON THIS ARENA panel (OPEN / FULL / CLOSED / NOT REPORTED /
  ARENA OFFLINE from the arena's own report, never guessing OPEN; logic.js
  `entryStatus`, `tests/entry.test.cjs`) with the commands to practise, benchmark
  and check readiness when entry is closed; live on 2026-10-05 it read CLOSED.
- [ ] Record the deployment, date and completed outside-fighter journey before
  closing this product milestone.

Resolve [AUD-029](AUD-029-starter-planner-new-moves.md) and
[AUD-030](AUD-030-onboarding-ruleset-consistency.md) before recommending the
starter to outside builders. Coordinate the guided path and cohort with
[AUD-035](AUD-035-first-session-onboarding.md) and
[AUD-039](AUD-039-builder-beta-and-commercial-evidence.md). Public code reuse
remains tracked by [AUD-028](AUD-028-licence.md).

**Sources:** [2026-09-25 product review](../reports/2026-09-25-product-review.md)
and [2026-09-30 product review](../reports/2026-09-30-product-review.md).
