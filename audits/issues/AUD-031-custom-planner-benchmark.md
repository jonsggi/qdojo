# AUD-031 — Benchmark a builder's own planner directly from the CLI

- **Status:** Open
- **Priority:** P1 — builder improvement loop
- **Type:** Feature
- **Scope:** combat/cli.py, combat/evaluate.py, combat/training.py, docs/build-a-bot.md

## Finding and impact

The evaluate command accepts built-in policies only. The builder guide's
section 4 tells users to write a separate Python script to evaluate their own
planner over multiple seeds. Single-fight training is insufficient to tell
whether an edit improves performance or merely wins one favorable seed.

## Acceptance criteria

- [ ] Add a documented planner-command evaluation mode alongside built-in policies.
- [ ] Reuse the existing subprocess limits and diagnostics, including timeouts,
  invalid output, adjusted plans and fallback reporting.
- [ ] Evaluate paired, side-swapped fights over reproducible seeds, with an explicit
  ruleset and opponent/pool selection.
- [ ] Report per-opponent W/D/L, aggregate score, fight count, seed suite, ruleset,
  and planner failure/fallback counts in human-readable and JSON output.
- [ ] Make repeated runs comparable, documenting that a nondeterministic external
  planner can still choose differently on identical observations.
- [ ] Distinguish training seeds from held-out evaluation seeds in the guide.
- [ ] Demonstrate comparing two versions of a custom planner using published commands.
- [ ] Check complete evaluations with a working planner and a failing planner;
  fallback games must not silently appear as successful planner executions.

## Related work

Use the consistent ruleset path from [AUD-030](AUD-030-onboarding-ruleset-consistency.md).
The beta measurement issue [AUD-039](AUD-039-builder-beta-and-commercial-evidence.md)
uses these comparisons as supporting evidence of improvement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
