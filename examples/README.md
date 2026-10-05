# Examples

| Path | What it is |
|---|---|
| [`combat/planner_minimal.py`](combat/planner_minimal.py) | A dependency-free planner: reads one observation and its `ruleset_digest` (candidates 1-3), answers the opponent's most common action, feints into blockers and makes a LAST STAND when behind (candidate 3), keeps its stamina affordable, powers a strike in the last round. The site serves an identical copy. Start here; see [Build a bot](../docs/build-a-bot.md) |

```sh
uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"
```

The riddle game's solvers, strategies and sample riddle were removed on
2026-09-28; they live at git tag `riddle-v0-final`.
