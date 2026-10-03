# AUD-030 — Align onboarding commands and explanations with the arena rules

- **Status:** Open; source inconsistencies rechecked 2026-10-03 at 2eb5ef8b
- **Priority:** P1 — before outside-builder onboarding
- **Type:** Bug / documentation
- **Scope:** combat/cli.py, README, builder/API guides, apps/web/llms.txt, website guide/join/help

## Finding and impact

The arena inspected on 2026-09-30 used candidate 3. However:

- train and evaluate default to candidate 1 in combat/cli.py.
- llms.txt lines 151–156 still recommend candidate 2 as the live arena's rules.
- The website's planner contract and builder guide list only the original moves,
  and parts of the guide teach candidate-1 HP, stamina and damage values.

A builder can practise a different game from the one they intend to enter.
Keeping historical rulesets available is necessary; presenting different
versions as the current onboarding path is the defect.

Some explanatory text also misstates candidate-3 behavior: the glossary says
FEINT baits RECOVER, although it earns no opening against it, and describes
LAST STAND as worth nothing while ahead even though it retains base damage.

## Acceptance criteria

- [ ] Define one explicit ruleset-selection policy for the public quickstart.
  Defaults may stay backward compatible if every arena-oriented command
  explicitly selects the correct version.
- [ ] README, builder guide, website, downloadable examples, and agent briefing
  agree on submitted moves, resource values, power rules and the selected version.
- [ ] CLI output identifies the selected version/digest before interpreting results.
- [ ] Historical instructions are clearly labelled; old replays retain their rules.
- [ ] Correct the FEINT and LAST STAND explanations against the normative artifact.
- [ ] Follow the published commands from a clean checkout and confirm the training
  ruleset matches the intended arena manifest.
- [ ] Include onboarding documentation and examples in the ruleset release checklist.

## Related work

Fix the starter separately in [AUD-029](AUD-029-starter-planner-new-moves.md).
[AUD-041](AUD-041-builder-journey-acceptance.md) provides the behavioral check;
argument-parser validation alone does not establish ruleset agreement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
