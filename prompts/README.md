# Prompts

| File | Used by | Game |
|---|---|---|
| [`combat/planner-system.md`](combat/planner-system.md) | `qdojo.combat.llm_planner` (see [Build a bot](../docs/build-a-bot.md) §7) | Combat, candidate 1 |
| [`combat/planner-system-candidate-2.md`](combat/planner-system-candidate-2.md) | the same planner, when the observation's `ruleset_digest` is candidate 2 (the live demo) | Combat, candidate 2 |
| [`combat/planner-system-claude.md`](combat/planner-system-claude.md), [`combat/planner-system-claude-candidate-2.md`](combat/planner-system-claude-candidate-2.md) | the CLAUDE lineup entry (`"prompt"`), candidate 1 and 2 | Combat |
| `solver-system.md`, `solver-user.md` | The legacy riddle solvers (`qdojo/prompts.py`, `examples/solvers/`) | Legacy riddle |

The riddle prompts keep their riddle semantics on purpose. Never send a riddle
prompt to a combat planner, or rename riddle answer fields to combat actions.
Changing these prompts changes how the live arena's LLM fighters play; their
rules summaries must stay consistent with [combat.md](../docs/combat.md). The
planner picks the `-candidate-2` sibling of the configured prompt by itself
when the fight's ruleset is candidate 2 (`llm_planner.prompt_for`), so a
lineup names only the base prompt.
