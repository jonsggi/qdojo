#!/usr/bin/env python3
"""One command for all three Qubic belts. Reads the riddle, looks at the
`family` field inside its input, and runs the matching solver next to this
file with the same riddle on stdin:

    qubic_transaction_audit  ->  qubic_transaction_audit.py  (orange)
    qubic_asset_ledger       ->  qubic_asset_ledger.py       (green)
    qubic_call_audit         ->  qubic_call_audit.py         (blue)

Anything else, including every classic family, is sat out: nothing is
printed and the bot does not commit. Use it as

    qdojo bot run --board URL --solver python3 examples/solvers/qubic_pack.py
"""
import json
import os
import subprocess
import sys

raw = sys.stdin.read()
try:
    family = json.loads(json.loads(raw)["input"]).get("family")
except (KeyError, TypeError, ValueError):
    family = None
if family not in ("qubic_transaction_audit", "qubic_asset_ledger", "qubic_call_audit"):
    sys.exit(0)
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), family + ".py")
p = subprocess.run([sys.executable, path], input=raw.encode("utf-8"), capture_output=True)
sys.stdout.write(p.stdout.decode("utf-8", "replace"))
sys.stderr.write(p.stderr.decode("utf-8", "replace"))
sys.exit(p.returncode)
