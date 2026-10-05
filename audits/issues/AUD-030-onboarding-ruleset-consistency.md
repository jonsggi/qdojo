# AUD-030 — Align onboarding commands and explanations with the arena rules

- **Status:** Fixed in d1d5ff5b and 7a0837c3 (V3 default, docs), release checklist in docs/operations.md §7 (AUD-041 commit)
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

- [x] Define one explicit ruleset-selection policy for the public quickstart.
  Defaults may stay backward compatible if every arena-oriented command
  explicitly selects the correct version. *Evidence:* `PUBLIC_ARENA` (candidate 3) is the default of train, evaluate and doctor; the quickstart never passes `--ruleset` (checked by `test_the_published_commands_select_the_public_arena_ruleset`).
- [x] README, builder guide, website, downloadable examples, and agent briefing
  agree on submitted moves, resource values, power rules and the selected version. *Evidence:* README, build-a-bot.md, api.md, glossary, llms.txt, the site's BUILD A BOT commands and the starter were updated to V3 in 7a0837c3.
- [x] CLI output identifies the selected version/digest before interpreting results. *Evidence:* train, evaluate and doctor print the ruleset line first (`test_human_report_names_the_ruleset_first`, the journey test's train step).
- [x] Historical instructions are clearly labelled; old replays retain their rules. *Evidence:* llms.txt and build-a-bot label V1/V2 historical; old replays verify under their own digest (`combat replay`, replaycheck).
- [x] Correct the FEINT and LAST STAND explanations against the normative artifact. *Evidence:* the help screen and glossary now say FEINT earns nothing against RECOVER and LAST STAND keeps its base damage while level or ahead (7a0837c3).
- [x] Follow the published commands from a clean checkout and confirm the training
  ruleset matches the intended arena manifest. *Evidence:* `tests/combat/test_builder_journey.py` runs doctor, train, evaluate, join and replay in-process from the checkout against a local demo-c3 arena and compares every digest with the arena manifest. It runs from the checkout, not from a fresh clone.
- [x] Include onboarding documentation and examples in the ruleset release checklist. *Evidence:* docs/operations.md §7, "Releasing a ruleset to the public arena".

## Related work

Fix the starter separately in [AUD-029](AUD-029-starter-planner-new-moves.md).
[AUD-041](AUD-041-builder-journey-acceptance.md) provides the behavioral check;
argument-parser validation alone does not establish ruleset agreement.

**Source:** [2026-09-30 product review](../reports/2026-09-30-product-review.md), recorded 2026-10-03.
