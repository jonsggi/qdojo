"""Pure hashing. No I/O.

The combat protocol's domain tags live with the code that uses them
(combat/codec.py, combat/rules.py); this is the one shared primitive.
"""
import hashlib


def sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.digest()
