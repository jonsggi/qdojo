# Prompts

| File | Used by | Ruleset |
|---|---|---|
| [`combat/planner-system.md`](combat/planner-system.md) | `qdojo.combat.llm_planner` (see [Build a bot](../docs/build-a-bot.md) §7) | candidate 1 |
| [`combat/planner-system-candidate-2.md`](combat/planner-system-candidate-2.md) | the same planner, when the observation's `ruleset_digest` is candidate 2 (the live demo) | candidate 2 |
| [`combat/planner-system-candidate-3.md`](combat/planner-system-candidate-3.md) | the same planner, when the observation's `ruleset_digest` is candidate 3 (LAST_STAND, FEINT) | candidate 3 |
| [`combat/planner-system-claude.md`](combat/planner-system-claude.md), [`combat/planner-system-claude-candidate-2.md`](combat/planner-system-claude-candidate-2.md), [`combat/planner-system-claude-candidate-3.md`](combat/planner-system-claude-candidate-3.md) | the CLAUDE lineup entry (`"prompt"`), candidates 1, 2 and 3 | all three |

Changing these prompts changes how the live arena's LLM fighters play; their
rules summaries must stay consistent with [combat.md](../docs/combat.md). The
planner picks the `-candidate-2` or `-candidate-3` sibling of the configured
prompt by itself when the fight's ruleset is candidate 2 or 3
(`llm_planner.prompt_for`), so a
lineup names only the base prompt.
