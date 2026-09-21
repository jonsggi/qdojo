#!/usr/bin/env python3
"""A deterministic fighter for the orange Qubic family, qubic_transaction_audit.

Written from the riddle statement alone: the statement carries the whole
rule, so this is what it says, in order. Each hex frame is a wire-format
Qubic transaction: an 80-byte header (32-byte source key, 32-byte
destination key, signed int64 amount, uint32 tick, uint16 inputType, uint16
inputSize, all little-endian), then inputSize payload bytes and a 64-byte
signature. A frame is retained only if it has at least 80 bytes, its total
length is exactly 80 + inputSize + 64, and its amount is between 0 and
MAX_AMOUNT inclusive. The retained frames are filtered by the query and one
metric is summed. Python integers do not wrap, which the statement requires.

Every clause here decides some instance: the amount is signed and can be
negative or above MAX_AMOUNT, the tick is unsigned and above 2^31, a frame
one byte short or long is rejected, and the source filter is only present
in some queries. Measured on 200 fresh instances for issue #17: 200 solved.

It sits out any riddle that is not this family, so it is safe to point at
every table; see qubic_pack.py to fight all three Qubic belts with one
command.
"""
import json
import struct
import sys

MAX_AMOUNT = 1_000_000_000_000_000
HEADER = "<32s32sqIHH"   # source, destination, amount, tick, inputType, inputSize

riddle = json.load(sys.stdin)
try:
    data = json.loads(riddle["input"])
except (KeyError, ValueError):
    data = {}
if data.get("family") != "qubic_transaction_audit":
    sys.exit(0)  # not ours: print nothing and the bot sits this round out

query = data["query"]
total = 0
for text in data["frames"]:
    try:
        frame = bytes.fromhex(text)
    except ValueError:
        continue
    if len(frame) < 80:
        continue
    source, destination, amount, tick, input_type, input_size = struct.unpack(HEADER, frame[:80])
    if len(frame) != 80 + input_size + 64:
        continue
    if not 0 <= amount <= MAX_AMOUNT:
        continue
    if destination.hex() != query["destination"] or input_type != query["input_type"]:
        continue
    if not query["tick_min"] <= tick <= query["tick_max"]:
        continue
    if "source" in query and source.hex() != query["source"]:
        continue
    if query["metric"] == "amount":
        total += amount
    elif query["metric"] == "count":
        total += 1
    elif query["metric"] == "payload_u64":
        payload = frame[80:80 + input_size]
        if len(payload) >= 8:
            total += struct.unpack("<Q", payload[:8])[0]
print(json.dumps({"answer": total}))
