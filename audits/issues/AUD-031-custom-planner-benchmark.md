# AUD-031 — Benchmark a builder's own planner directly from the CLI

- **Status:** Fixed in d1d5ff5b (`qdojo combat evaluate --planner`) and 7a0837c3 (guide)
- **Priority:** P1 — builder improvement loop
- **Type:** Feature
- **Scope:** combat/cli.py, combat/evaluate.py, combat/training.py, docs/build-a-bot.md

## Finding and impact

The evaluate command accepts built-in policies only. The builder guide's
section 4 tells users to write a separate Python script to evaluate their own
planner over multiple seeds. Single-fight training is insufficient to tell
whether an edit improves performance or merely wins one favorable seed.

## Acceptance criteria

- [x] Add a documented planner-command evaluation mode alongside built-in policies. *Evidence:* `evaluate --planner CMD`, documented in build-a-bot.md §4 and llms.txt.
- [x] Reuse the existing subprocess limits and diagnostics, including timeouts,
  invalid output, adjusted plans and fallback reporting. *Evidence:* the same `planner.run_or_fallback` limits as train; failures counted by kind.
- [x] Evaluate paired, side-swapped fights over reproducible seeds, with an explicit
  ruleset and opponent/pool selection. *Evidence:* side-swapped seed pairs per opponent, `--suite`, `--opponent`/pool, explicit `--ruleset`.
- [x] Report per-opponent W/D/L, aggregate score, fight count, seed suite, ruleset,
  and planner failure/fallback counts in human-readable and JSON output. *Evidence:* human table and JSON `qdojo.combat.evaluation.v1` (`test_evaluate_a_planner_and_compare_two_versions`).
- [x] Make repeated runs comparable, documenting that a nondeterministic external
  planner can still choose differently on identical observations. *Evidence:* `test_evaluation_is_reproducible_and_seed_suites_differ`; the guide notes a random or model-backed planner still varies.
- [x] Distinguish training seeds from held-out evaluation seeds in the guide. *Evidence:* build-a-bot.md §4, "Tune on one seed suite, report on another".
- [x] Demonstrate comparing two versions of a custom planner using published commands. *Evidence:* `--planner` twice gives a paired difference with a 95% interval; guide and llms.txt show the command.
- [x] Check complete evaluations with a working planner and a failing planner;
  fallback games must not silently appear as successful planner executions. *Evidence:* a failing planner makes evaluate exit 1 with every fallback counted, never a silent success (same test).

## Related work

Use the consistent ruleset path from [AUD-030](AUD-030-onboarding-ruleset-consistency.md).
The beta measurement issue [AUD-039](AUD-039-builder-beta-and-commercial-evidence.md)
uses these comparisons as supporting evidence of improvement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
