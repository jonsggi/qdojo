#!/usr/bin/env python3
"""NPC that always answers, always wrong-shaped-but-valid. Measures the floor."""
import json, sys
r = json.load(sys.stdin)
print(json.dumps({"answer": {"integer": -1, "string": "kobold", "hex": "00"}[r["answer_format"]]}))
