#!/usr/bin/env python3
"""NPC that solves only the simplest sums, and only after a nap. Shows what
first-wins does to a slow but correct fighter. Env SLOW_SECONDS (default 75)."""
import json, os, sys, time
r = json.load(sys.stdin)
time.sleep(float(os.environ.get("SLOW_SECONDS", "75")))
if r["answer_format"] == "integer" and "sum" in r["statement"].lower():
    nums = [int(x) for x in r["input"].split() if x.strip().lstrip("-").isdigit()]
    print(json.dumps({"answer": sum(nums)}))
else:
    print(json.dumps({"answer": -1}))
