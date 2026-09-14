#!/usr/bin/env python3
"""The simplest solver: sums the numbers in `input`. Reads the riddle JSON on
stdin, prints {"answer": ...}. Replace the middle with your own bot."""
import json
import sys

riddle = json.load(sys.stdin)
if riddle["answer_format"] == "integer":
    nums = [int(x) for x in riddle["input"].split() if x.strip().lstrip("-").isdigit()]
    print(json.dumps({"answer": sum(nums)}))
else:
    print(json.dumps({"answer": ""}))
