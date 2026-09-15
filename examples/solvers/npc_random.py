#!/usr/bin/env python3
"""NPC that guesses. Right by accident once in a blue moon on tiny answer spaces."""
import json, random, sys
r = json.load(sys.stdin)
fmt = r["answer_format"]
ans = random.randint(0, 1000) if fmt == "integer" else (random.choice(["dojo", "sensei", "kata", "kumite"]) if fmt == "string" else "%02x" % random.randint(0, 255))
print(json.dumps({"answer": ans}))
