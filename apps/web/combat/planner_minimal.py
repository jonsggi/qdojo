#!/usr/bin/env python3
"""A dependency-free combat planner (docs/api.md section 1).

Reads one qdojo.combat.observation.v1 object on stdin and prints one
qdojo.combat.plan.v1 object. Run it against an NPC under the public arena's
rules (V3, combat-v1-candidate-3, the default of `qdojo combat train`):

    uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"

Strategy, deliberately simple: count what the opponent actually did in the
earlier rounds of this fight and answer the most common action; every third
beat, play a filler that sets up or catches up (FEINT into a blocker or a
ducker, LAST_STAND when trailing, else JAB); keep enough stamina for the plan
to stay affordable; power the first affordable strike of the last round.

The observation names its ruleset (ruleset_digest). This file knows the three
packaged rulesets; under any other it stops with a clear message on stderr
(the runner then plays its fallback) instead of guessing at numbers.
Diagnostics go to stderr, never stdout.
"""
import json
import sys

BASE = ("JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER")
COST = {"JAB": 6, "KICK": 12, "BLOCK": 4, "DUCK": 4, "THROW": 9, "RECOVER": 0,
        "LAST_STAND": 8, "FEINT": 2}
# What differs between the packaged rulesets, by digest (rulesets/{digest}.json).
RULESETS = {
    "12085c86a61ffd106430b6690acbd522c5a94f90ed8024585817f4939fe4842c":
        {"name": "combat-v1-candidate-1", "max_stamina": 60, "moves": BASE},
    "231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b74":
        {"name": "combat-v1-candidate-2", "max_stamina": 48, "moves": BASE},
    "cf19b7cfee8ccbdd2a3bbf31132f8327eab63a5341ca7528d682353c32c01bf4":
        {"name": "combat-v1-candidate-3", "max_stamina": 48, "moves": BASE + ("LAST_STAND", "FEINT")},
}
# The same under all three: +2 stamina after any executed move except RECOVER
# (+18 if unhit), +3 per consecutive BLOCK, +4 to power a strike.
STEP, RECOVER_GAIN, STREAK, POWER_COST, RESERVE = 2, 18, 3, 4, 8
ANSWER = {                 # a cheap action that beats each opponent action
    "JAB": "DUCK",         # evades and earns an opening
    "KICK": "JAB",         # out-trades it for half the stamina
    "BLOCK": "THROW",      # breaks the guard
    "DUCK": "KICK",
    "THROW": "JAB",        # interrupts it
    "RECOVER": "KICK",
    "LAST_STAND": "BLOCK",  # stops it, bonus and all
    "FEINT": "JAB",        # a glancing hit, and no guard-break opening for them
}
STRIKES = ("JAB", "KICK", "THROW")   # the only actions that may carry power


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def cost(action, streak, power=False):
    return COST[action] + (STREAK * streak if action == "BLOCK" else 0) + (POWER_COST if power else 0)


def project(actions, stamina, streak, cap, power_slot=-1):
    """Lowest stamina left after paying for any beat; negative means EXHAUSTED somewhere."""
    low = stamina
    for i, a in enumerate(actions):
        paid = cost(a, streak, i == power_slot)
        low = min(low, stamina - paid)
        stamina = min(cap, stamina - paid + (RECOVER_GAIN if a == "RECOVER" else STEP))
        streak = streak + 1 if a == "BLOCK" else 0
    return low


def main():
    obs = json.load(sys.stdin)
    digest = obs.get("ruleset_digest")
    rules = RULESETS.get(digest)
    if rules is None:
        fail(f"planner_minimal: unsupported ruleset_digest {digest!r}; this starter knows "
             f"{', '.join(r['name'] for r in RULESETS.values())}. Fetch rulesets/{{digest}}.json from the "
             f"arena export and add its numbers to RULESETS.")
    moves, cap = rules["moves"], rules["max_stamina"]
    me, opp = obs["self"], obs["opponent"]
    other = "B" if obs["self_slot"] == "A" else "A"
    seen = {}
    for r in obs["prior_rounds"]:
        for beat in r["beats"]:
            a = beat[other]["effective"]
            if a in COST:                         # EXHAUSTED is not a habit
                seen[a] = seen.get(a, 0) + 1
    likely = max(seen, key=lambda k: (seen[k], k)) if seen else "JAB"
    answer = ANSWER.get(likely, "JAB")
    behind = opp["hp"] - me["hp"]
    if "FEINT" in moves and likely in ("BLOCK", "DUCK"):
        filler = "FEINT"        # baits the guard: the next beat's strike gets the opening
    elif "LAST_STAND" in moves and behind >= 8 and likely != "BLOCK":
        filler = "LAST_STAND"   # +1 damage per HP behind, up to +16
    else:
        filler = "JAB"
    stamina, streak = me["stamina"], me["guard_streak"]
    actions = []
    for i in range(6):
        want = answer if i % 3 != 2 else filler
        if stamina - cost(want, streak) < RESERVE:
            want = "RECOVER"
        stamina = min(cap, stamina - cost(want, streak) + (RECOVER_GAIN if want == "RECOVER" else STEP))
        streak = streak + 1 if want == "BLOCK" else 0
        actions.append(want)
    assert all(a in moves for a in actions)
    power = -1
    if obs["round_index"] == 2 and me["power_available"]:
        power = next((i for i, a in enumerate(actions) if a in STRIKES
                      and project(actions, me["stamina"], me["guard_streak"], cap, i) >= 0), -1)
    print(f"{rules['name']}: expecting {likely}, answering {answer}, filler {filler}", file=sys.stderr)
    print(json.dumps({"schema": "qdojo.combat.plan.v1", "actions": actions, "power_slot": power}))


if __name__ == "__main__":
    main()
