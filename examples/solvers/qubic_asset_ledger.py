#!/usr/bin/env python3
"""A deterministic fighter for the green Qubic family, qubic_asset_ledger.

Written from the riddle statement alone. A holding lives in a slot
(issuer, name, owner, possessor, manager); the initial records are
fragmented and summed per slot. Each journal event names its exact from
slot and its shares, and the destination is derived the way the statement
says: a transfer moves ownership and possession together, so the recipient
becomes both owner and possessor under the same manager; a management event
changes only the manager. Events are replayed in journal order. When the
journal is settled every event carries a status and rejected ones do
nothing; when it is not, an event applies iff its from slot holds at least
its shares at that moment, which is why the replay must be sequential. The
query sums one asset's shares where the named role equals the identity,
optionally under one manager.

Measured on 200 fresh instances for issue #17: 200 solved. It sits out any
riddle that is not this family; see qubic_pack.py to fight all three Qubic
belts with one command.
"""
import json
import sys

FIELDS = ("issuer", "name", "owner", "possessor", "manager")

riddle = json.load(sys.stdin)
try:
    data = json.loads(riddle["input"])
except (KeyError, ValueError):
    data = {}
if data.get("family") != "qubic_asset_ledger":
    sys.exit(0)  # not ours: print nothing and the bot sits this round out


def key(slot):
    return tuple(slot[f] for f in FIELDS)


held = {}
for row in data["initial"]:
    held[key(row["slot"])] = held.get(key(row["slot"]), 0) + row["shares"]

for event in data["journal"]:
    source = key(event["from"])
    issuer, name, owner, possessor, manager = source
    if event["operation"] == "transfer":
        destination = (issuer, name, event["recipient"], event["recipient"], manager)
    else:
        destination = (issuer, name, owner, possessor, event["new_manager"])
    shares = event["shares"]
    if data["settled"]:
        applied = event["status"] == "applied"
    else:
        applied = held.get(source, 0) >= shares
    if applied:
        held[source] = held.get(source, 0) - shares
        held[destination] = held.get(destination, 0) + shares

query = data["query"]
role = FIELDS.index(query["role"])
total = 0
for slot, shares in held.items():
    if slot[0] != query["issuer"] or slot[1] != query["name"] or slot[role] != query["identity"]:
        continue
    if query["manager"] is not None and slot[4] != query["manager"]:
        continue
    total += shares
print(json.dumps({"answer": total}))
