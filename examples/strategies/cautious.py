#!/usr/bin/env python3
"""A default strategy: fight at your own belt, and one belt up only while
you can afford to lose a few. Reads the strategy context (docs/api.md) on
stdin, prints {"enter": bool, "why": str}. Env CAUTIOUS_REACH (belts above
your own you will try, default 1), CAUTIOUS_RESERVE (stakes to keep, default 3)."""
import json
import os
import sys

BELTS = ["white", "yellow", "orange", "green", "blue"]
ctx = json.load(sys.stdin)
rd, me = ctx["round"], ctx["me"]
reach = int(os.environ.get("CAUTIOUS_REACH", "1"))
reserve = int(os.environ.get("CAUTIOUS_RESERVE", "3"))
riddle_rank = BELTS.index(rd["belt"]) if rd.get("belt") in BELTS else None
my_rank = int(me.get("rank", 0))
bal, fee = me.get("balance"), rd["entry_fee"]
if riddle_rank is None:
    print(json.dumps({"enter": True, "why": "open table"})); sys.exit()
if riddle_rank > my_rank + reach:
    print(json.dumps({"enter": False, "why": f"{rd['belt']} is {riddle_rank - my_rank} belts above me"})); sys.exit()
if riddle_rank > my_rank and bal is not None and bal < fee * (reserve + 1):
    print(json.dumps({"enter": False, "why": "above my belt and my purse is thin"})); sys.exit()
print(json.dumps({"enter": True, "why": "my belt"}))
