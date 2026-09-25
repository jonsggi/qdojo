# Examples

| Path | Game | What it is |
|---|---|---|
| [`combat/planner_minimal.py`](combat/planner_minimal.py) | **Combat** | A dependency-free planner: reads one observation, answers the opponent's most common action, powers a strike in the last round. Start here; see [Build a bot](../docs/build-a-bot.md) |
| `solvers/` | Legacy riddle | Riddle solvers (plain, prompted, model-backed) and deliberately bad NPC solvers used by the old tests |
| `strategies/cautious.py` | Legacy riddle | An entry strategy for the riddle belts |
| `riddles/0001.json` | Legacy riddle | A sample riddle |

Legacy examples are kept because the riddle code and its tests still use them.
They do not work with `qdojo combat`.

```sh
uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"
```
