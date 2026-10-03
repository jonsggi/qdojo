# AUD-029 — Make the starter planner compatible with every supported ruleset

- **Status:** Open; reproduced again 2026-10-03 at 2eb5ef8b
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

- [ ] Both advertised copies handle every submitted move in supported rulesets.
- [ ] Resource projections and action choices use the observation's ruleset;
  an unsupported digest produces a clear diagnostic.
- [ ] Complete candidate-3 fights against opponents using both new moves finish
  without planner errors or fallback; old supported rulesets still work.
- [ ] Low stamina, spent power, and mixed prior-round histories are covered.
- [ ] The download and repository example cannot silently diverge.

## Related work

Coordinate with [AUD-030](AUD-030-onboarding-ruleset-consistency.md) and exercise
the supplied planner in [AUD-041](AUD-041-builder-journey-acceptance.md).

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
