# Prompts

| File | Used by | Game |
|---|---|---|
| [`combat/planner-system.md`](combat/planner-system.md) | `qdojo.combat.llm_planner` (see [Build a bot](../docs/build-a-bot.md) §7) | Combat |
| `solver-system.md`, `solver-user.md` | The legacy riddle solvers (`qdojo/prompts.py`, `examples/solvers/`) | Legacy riddle |

The riddle prompts keep their riddle semantics on purpose. Never send a riddle
prompt to a combat planner, or rename riddle answer fields to combat actions.
Changing `combat/planner-system.md` changes how the live arena's LLM fighters
play; its rules summary must stay consistent with [combat.md](../docs/combat.md).
