# Combat pivot: implementation handoff (2026-09-22)

> **Purpose:** the briefing given to implementation agents at the start of the combat pivot. \
> **Audience:** historians of the project. \
> **Status:** historical. Moved from the repository root (`GPT6_HANDOFF.md`) on 2026-09-25. Its statement that gameplay and live data are still riddle code is no longer true; for the current state read the [docs index](../README.md) and the [roadmap](../roadmap.md).

Updated 2026-09-22; combat direction specified 2026-09-21. This replaces the prior riddle-pack handoff, preserved
[in the archive](riddle-v0/GPT6_HANDOFF.md).

The user requested a detailed, explicit combat specification and alignment
of all documentation. They also requested actual NPC opponents, including a
random bot. This handoff concerns that direction; do not resume the old
riddle catalogue as the launch centerpiece.

## Read first

1. [Specification and authority](../spec.md).
2. [Exact combat rules](../combat.md) and [parameter artifact](../combat-v1.json).
3. [Protocol](../protocol.md), [matchmaking](../matchmaking.md),
   [competition](../competition.md).
4. [API](../api.md), [NPCs](../npcs.md), [validation](../model.md).
5. [Implementation packages](../pivot-plan.md) and [roadmap](../roadmap.md).

## What has and has not changed

Active documentation now describes combat. The old documents and signed
briefing are archived. Production Python/JS gameplay and live data remain
legacy riddle code. No new paid combat, contract, asset issuance, deployment,
signature, transaction, commit or merge is implied by this handoff.

A small executable reference under docs/reference exists to validate candidate
arithmetic and aid independent implementations. It is not the production engine,
does not move money, and does not establish strategic balance.

## Implement first

P0 schemas/fixtures, P1 independent combat cores, P2 free NPC training, then
P3 adversarial strategic validation. Three combat rounds carry state;
best-of-three series reset state between whole fights. These must not be confused.

The candidate has six actions, guard fatigue, opening opportunities and
one optional power strike per fight. Settlement has no RNG; random NPC/policy
choices are private off-chain decisions committed like player moves.

Use the exact step order, matrix and commitment encoding. Handle draws,
simultaneous KO, exhaustion, forfeits, double faults, ownership transfers,
expiry/cancellation and refunds as written. Do not borrow riddle semantics.

## Validation commands

These are local development checks, not live operations:

```sh
python3 docs/reference/combat_v1.py --check --smoke
python3 docs/reference/check_docs.py
make test
```

The smoke tournament is illustrative, not the full balance gate. Record
observed results; never report future gates as already passed.

Observed checks and their limits are recorded in
[validation-status.md](../validation-status.md). Read that before claiming
balance or contract readiness.

## Workspace care

Preserve .claude/, .infisical.json, private state, live exported records and
other worktrees. Existing financial/asset audit findings still require
disposition. Production values are in the decision register; do not guess
real contract indices, keys, addresses, registration prices or governance steps.
