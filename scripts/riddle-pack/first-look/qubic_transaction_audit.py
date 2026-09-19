#!/usr/bin/env python3
"""First-look solver for qubic_transaction_audit, frozen for the tool-reuse
measurement (Refs #17). Written from the statement while looking at one
instance (rng seed 1900001: metric payload_u64, no source filter, a width-0
tick range) and never edited afterwards. The shipped solver lives in
examples/solvers/. Do not fix this file; it is a record."""
import json
import struct
import sys

riddle = json.load(sys.stdin)
data = json.loads(riddle["input"])
q = data["query"]
MAX_AMOUNT = 1000000000000000

total = 0
for text in data["frames"]:
    frame = bytes.fromhex(text)
    if len(frame) < 80:
        continue
    src, dst, amount, tick, input_type, input_size = struct.unpack("<32s32sqIHH", frame[:80])
    if len(frame) != 80 + input_size + 64:
        continue
    if not 0 <= amount <= MAX_AMOUNT:
        continue
    if dst.hex() != q["destination"] or input_type != q["input_type"]:
        continue
    if not q["tick_min"] <= tick <= q["tick_max"]:
        continue
    if "source" in q and src.hex() != q["source"]:
        continue
    if q["metric"] == "amount":
        total += amount
    elif q["metric"] == "count":
        total += 1
    elif q["metric"] == "payload_u64":
        payload = frame[80:80 + input_size]
        if len(payload) >= 8:
            total += struct.unpack("<Q", payload[:8])[0]
print(json.dumps({"answer": total}))
