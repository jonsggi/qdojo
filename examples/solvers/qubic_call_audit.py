#!/usr/bin/env python3
"""A deterministic fighter for the blue Qubic family, qubic_call_audit.

Written from the riddle statement alone; the buggy_auditor pseudocode in the
input is never read, because the statement gives the intended rule in full.
Each transaction is a trace of enter/audit/exit events. A stack of frames
gives the three facts an audit needs: the originator is the transaction's
user throughout, the invocator is the parent frame's contract (or the user
at the top level), and invocationReward is the reward on the current frame,
restored when a child returns. An audit is accepted iff the originator
equals allowed and the current reward is at least the fee; it then refunds
reward minus fee to the invocator and credits the reward to the originator.
A transaction is invalid, and all its audits are discarded, if any nested
enter names a contract index that is not lower than the frame it is
entered from. The query then counts accepted audits or sums refunds or
credits to one identity.

Measured on 200 fresh instances for issue #17: 200 solved. It sits out any
riddle that is not this family; see qubic_pack.py to fight all three Qubic
belts with one command.
"""
import json
import sys

riddle = json.load(sys.stdin)
try:
    data = json.loads(riddle["input"])
except (KeyError, ValueError):
    data = {}
if data.get("family") != "qubic_call_audit":
    sys.exit(0)  # not ours: print nothing and the bot sits this round out

query = data["query"]
total = 0
for tx in data["transactions"]:
    originator = tx["originator"]
    stack, valid, receipts = [], True, []
    for event in tx["events"]:
        if event["op"] == "enter":
            if stack and event["contract"] >= stack[-1]["contract"]:
                valid = False  # keep walking: the trace still has to be popped to its end
            stack.append(event)
        elif event["op"] == "exit":
            stack.pop()
        elif event["op"] == "audit":
            invocator = originator if len(stack) == 1 else "C%d" % stack[-2]["contract"]
            reward = stack[-1]["reward"]
            if originator == event["allowed"] and reward >= event["fee"]:
                receipts.append((invocator, reward, reward - event["fee"]))
    if not valid:
        continue
    for invocator, reward, refund in receipts:
        if query["metric"] == "accepted":
            total += 1
        elif query["metric"] == "refund" and invocator == query["identity"]:
            total += refund
        elif query["metric"] == "credited" and originator == query["identity"]:
            total += reward
print(json.dumps({"answer": total}))
