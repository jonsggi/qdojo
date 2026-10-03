# AUD-027 — Outside builders cannot enter the arena

- **Status:** Implementation mitigated in 7557e2a and cb5a22d; product milestone remains open. Built and tested locally; outside entry was disabled at the 2026-09-30 review.
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

- [ ] Publish the beta entry policy, participant limits and eligibility for
  events against house bots, with accurate house/outside disclosure.
- [ ] Configure and enable the intended free beta entry path using the documented
  operator switches; verify limits, useful rejection messages and recovery from
  an interrupted registration on that deployment.
- [ ] Have an independent builder follow the public instructions, register a
  fighter, complete a combat fight and open its verified replay.
- [ ] Show the deployment's entry availability on the builder page, including
  a useful next step when registration is closed.
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
