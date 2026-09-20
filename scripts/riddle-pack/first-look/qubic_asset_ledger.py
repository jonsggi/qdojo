#!/usr/bin/env python3
"""First-look solver for qubic_asset_ledger, frozen for the tool-reuse
measurement (Refs #17). Written from the statement while looking at one
instance (rng seed 1900001: settled, role possessor, manager 1) and never
edited afterwards. The shipped solver lives in examples/solvers/. Do not fix
this file; it is a record."""
import json
import sys

riddle = json.load(sys.stdin)
data = json.loads(riddle["input"])
q = data["query"]
FIELDS = ("issuer", "name", "owner", "possessor", "manager")


def key(slot):
    return tuple(slot[f] for f in FIELDS)


held = {}
for row in data["initial"]:
    k = key(row["slot"])
    held[k] = held.get(k, 0) + row["shares"]

for event in data["journal"]:
    src = key(event["from"])
    issuer, name, owner, possessor, manager = src
    if event["operation"] == "transfer":
        dst = (issuer, name, event["recipient"], event["recipient"], manager)
    else:
        dst = (issuer, name, owner, possessor, event["new_manager"])
    shares = event["shares"]
    if data["settled"]:
        applied = event["status"] == "applied"
    else:
        applied = held.get(src, 0) >= shares
    if applied:
        held[src] = held.get(src, 0) - shares
        held[dst] = held.get(dst, 0) + shares

role = FIELDS.index(q["role"])
total = 0
for k, n in held.items():
    if k[0] != q["issuer"] or k[1] != q["name"] or k[role] != q["identity"]:
        continue
    if q["manager"] is not None and k[4] != q["manager"]:
        continue
    total += n
print(json.dumps({"answer": total}))
