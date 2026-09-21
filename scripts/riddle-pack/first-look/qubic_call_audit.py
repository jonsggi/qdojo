#!/usr/bin/env python3
"""First-look solver for qubic_call_audit, frozen for the tool-reuse
measurement (Refs #17). Written from the statement while looking at one
instance (rng seed 1900001: metric accepted, identity U1) and never edited
afterwards. The shipped solver lives in examples/solvers/. Do not fix this
file; it is a record."""
import json
import sys

riddle = json.load(sys.stdin)
data = json.loads(riddle["input"])
q = data["query"]

total = 0
for tx in data["transactions"]:
    originator = tx["originator"]
    stack, valid, accepted = [], True, []
    for event in tx["events"]:
        if event["op"] == "enter":
            if stack and event["contract"] >= stack[-1]["contract"]:
                valid = False
            stack.append(event)
        elif event["op"] == "exit":
            stack.pop()
        elif event["op"] == "audit":
            invocator = originator if len(stack) == 1 else "C%d" % stack[-2]["contract"]
            reward = stack[-1]["reward"]
            if originator == event["allowed"] and reward >= event["fee"]:
                accepted.append((originator, invocator, reward, reward - event["fee"]))
    if not valid:
        continue
    for who, invocator, reward, refund in accepted:
        if q["metric"] == "accepted":
            total += 1
        elif q["metric"] == "refund" and invocator == q["identity"]:
            total += refund
        elif q["metric"] == "credited" and who == q["identity"]:
            total += reward
print(json.dumps({"answer": total}))
