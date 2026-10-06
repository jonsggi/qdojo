# AUD-029 — Make the starter planner compatible with every supported ruleset

- **Status:** Fixed in d1d5ff5b (starter), 2a58d45a (wording); regression tests in tests/combat/test_starter.py
- **Priority:** P1 — before outside-builder onboarding
- **Type:** Bug
- **Scope:** examples/combat/planner_minimal.py, apps/web/combat/planner_minimal.py, planner examples and tests

## Finding and impact

The advertised starter counts the opponent's effective actions and indexes
`ANSWER[likely]`. ANSWER contains only the six original submitted actions.
When LAST_STAND or FEINT is most frequent, the process exits with a KeyError.
The runner then uses its fallback, so a builder following the instructions can
lose rounds because the supplied example is incompatible with the arena.

The example also hard-codes candidate-1 recovery and stamina-cap values.
Adding two dictionary entries alone would leave its resource budgeting wrong
under candidates 2 and 3.

## Reproduction

From the repository root, this exercises the observation fields the starter reads:

```sh
python3 - <<'PY'
import json, subprocess
for action in ["JAB", "LAST_STAND", "FEINT"]:
    obs = {
        "self": {"stamina": 48, "power_available": True},
        "self_slot": "A", "round_index": 1,
        "prior_rounds": [{"beats": [{"B": {"effective": action}}]}],
    }
    result = subprocess.run(
        ["python3", "examples/combat/planner_minimal.py"],
        input=json.dumps(obs), text=True, capture_output=True,
    )
    print(action, result.returncode,
          result.stdout.strip() or result.stderr.splitlines()[-1])
PY
```

Observed: JAB exits 0; LAST_STAND and FEINT exit 1 with their respective
KeyErrors. Use full engine-produced observations for the regression fixtures.

## Acceptance criteria

- [x] Both advertised copies handle every submitted move in supported rulesets. *Evidence:* both copies know candidates 1-3 and answer LAST_STAND and FEINT; the 2026-10-03 reproduction now ends in a clear diagnostic (its hand-written observation has no ruleset_digest) instead of a KeyError.
- [x] Resource projections and action choices use the observation's ruleset;
  an unsupported digest produces a clear diagnostic. *Evidence:* stamina caps and move sets per ruleset come from `ruleset_digest`; an unknown digest exits 2 naming the known rulesets (`test_an_unsupported_ruleset_is_a_clear_diagnostic`).
- [x] Complete candidate-3 fights against opponents using both new moves finish
  without planner errors or fallback; old supported rulesets still work. *Evidence:* `test_complete_fights_never_fall_back_or_get_adjusted` (stander, feinter and three scripted new-move users, every supported ruleset) and the builder journey of AUD-041.
- [x] Low stamina, spent power, and mixed prior-round histories are covered. *Evidence:* `test_low_stamina_spent_power_and_mixed_histories`.
- [x] The download and repository example cannot silently diverge. *Evidence:* `test_the_download_is_the_repository_example` requires the two files to be identical; the AUD-041 journey runs both.

## Related work

Coordinate with [AUD-030](AUD-030-onboarding-ruleset-consistency.md) and exercise
the supplied planner in [AUD-041](AUD-041-builder-journey-acceptance.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
