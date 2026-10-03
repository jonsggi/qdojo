# AUD-040 — Split the frontend controller into modules with clear ownership

- **Status:** Open
- **Priority:** P2 — maintainability
- **Type:** Refactor
- **Scope:** apps/web/combat/app.js, index.html script loading, browser tests

## Finding and impact

At 2eb5ef8b, combat/app.js is 3,101 lines and 251,005 bytes. It contains routing,
data access, many page renderers, replay control, practice, collection views,
event wiring and shared mutable state. Changes to one user journey are harder
to review and isolate as the application grows.

The existing separate engine, logic and stage modules already provide useful
boundaries. Preserve and extend them.

## Acceptance criteria

- [ ] Extract coherent modules for routing/lifecycle, data access, replay, practice,
  and collection/fighter views, with explicit dependencies and state ownership.
- [ ] Define where timers, listeners and players are created and disposed so route
  changes and periodic refreshes do not reset playback or leak work.
- [ ] Preserve engine determinism, verification semantics, historical rulesets and
  live-to-sample fallback behavior.
- [ ] Make the work incremental and reviewable; a framework migration is not required.
- [ ] Verify deep links, polling during replay, practice state, collection views,
  responsive layout and keyboard/reduced-motion behavior.
- [ ] Keep the established static deployment path working and document any
  intentional build or loading changes.

## Related work

[AUD-041](AUD-041-builder-journey-acceptance.md) supplies behavior-oriented
coverage. This refactor can proceed incrementally alongside the UX issues and
does not block fixing the starter or opening the beta by itself.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
