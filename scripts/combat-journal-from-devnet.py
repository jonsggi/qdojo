#!/usr/bin/env python3
"""Turn a devnet's journal (e.g. the live arena's) into a parity journal.

  combat-journal-from-devnet.py DEVNET_DIR OUT.journal [--max-ticks N]

A devnet keeps its manifest in devnet.json and its records in devnet.journal;
the C++ ports read one file whose first line is the manifest header
(store.header) and whose last record is the reference's event digest. This
writes that file, cut at the last `digest` checkpoint the devnet recorded (or
the last one before --max-ticks), so the reference digest is the devnet's own.
Reads DEVNET_DIR only; never writes there. The output is not committed: the
live arena's journal is ~100 MB. Replay it with

  contracts/combat_contract/test_contract_c3 OUT.journal
  QDOJO_EXTRA_JOURNALS=OUT.journal make qubic-core-test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import devnet, store  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("devnet_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--max-ticks", type=int, default=0, help="cut at the last checkpoint at or before this tick")
    a = ap.parse_args()
    meta = json.loads((a.devnet_dir / "devnet.json").read_text())
    _, _, m = devnet.recorded(meta)
    lines = (a.devnet_dir / devnet.JOURNAL).read_text(encoding="utf-8").split("\n")
    keep, last = [], None
    for line in lines:
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            break                                   # a record still being appended
        if a.max_ticks and rec.get("t", 0) > a.max_ticks:
            break
        keep.append(line)
        if rec["k"] == "digest":
            last = len(keep)
    if last is None:
        sys.exit("no digest checkpoint in that journal")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(store.header(m)) + "\n")
        for line in keep[:last]:
            f.write(line + "\n")
    tail = json.loads(keep[last - 1])
    print(f"{a.out}: {last} records up to tick {tail['t']}, ruleset {m.ruleset.digest.hex()[:16]}..., "
          f"event_seq {tail['event_seq']}, digest {tail['event_digest']}")


if __name__ == "__main__":
    main()
