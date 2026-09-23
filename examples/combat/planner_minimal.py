#!/usr/bin/env python3
"""A dependency-free combat planner (docs/api.md §1).

Reads one qdojo.combat.observation.v1 object on stdin and prints one
qdojo.combat.plan.v1 object. Run it against an NPC:

    uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"

Strategy, deliberately simple: count what the opponent actually did in the
earlier rounds of this fight and answer the most common action; keep enough
stamina for the plan to stay affordable; use the power strike in the last
round. Diagnostics go to stderr, never stdout.
"""
import json
import sys

COST = {"JAB": 6, "KICK": 12, "BLOCK": 4, "DUCK": 4, "THROW": 9, "RECOVER": 0}
ANSWER = {           # a cheap action that beats each opponent action
    "JAB": "DUCK",   # evades and earns an opening
    "KICK": "JAB",   # trades 8 for 14 but costs half
    "BLOCK": "THROW",
    "DUCK": "KICK",
    "THROW": "JAB",
    "RECOVER": "KICK",
}


def main():
    obs = json.load(sys.stdin)
    me = obs["self"]
    other = "B" if obs["self_slot"] == "A" else "A"
    seen = {}
    for r in obs["prior_rounds"]:
        for beat in r["beats"]:
            a = beat[other]["effective"]
            if a != "EXHAUSTED":
                seen[a] = seen.get(a, 0) + 1
    likely = max(seen, key=lambda k: (seen[k], k)) if seen else "JAB"
    stamina = me["stamina"]
    actions = []
    for i in range(6):
        want = ANSWER[likely] if i % 3 != 2 else "JAB"
        if stamina - COST[want] < 8:
            want = "RECOVER"
        stamina = min(60, stamina - COST[want] + (18 if want == "RECOVER" else 2))
        actions.append(want)
    power = -1
    if obs["round_index"] == 2 and me["power_available"]:
        power = next((i for i, a in enumerate(actions) if a in ("JAB", "KICK", "THROW")), -1)
    print(f"expecting {likely}", file=sys.stderr)
    print(json.dumps({"schema": "qdojo.combat.plan.v1", "actions": actions, "power_slot": power}))


if __name__ == "__main__":
    main()
