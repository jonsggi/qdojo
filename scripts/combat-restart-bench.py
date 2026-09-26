#!/usr/bin/env python3
"""Restart cost of a demo arena, measured on a COPY of its directory.

Copies the arena's devnet files to a scratch directory (the source is only
read), then measures what a restart costs:
1. a full journal replay (what every restart did before snapshots; with this
   code it also compacts finished history while it replays);
2. with snapshot support: writing a snapshot, then a restart from it.
Reports wall and CPU seconds, peak memory and what stays in memory, and
checks that both paths reach the same event digest.

  uv run python scripts/combat-restart-bench.py ~/.qdojo/combat/arena --scratch /tmp/bench

Set QDOJO_SRC to an older source tree (its packages/qdojo/src) to measure the
code before snapshots; the steps it cannot run there are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("QDOJO_SRC", str(ROOT / "packages/qdojo/src")))

from qdojo.combat import devnet  # noqa: E402

FILES = ("devnet.journal", "devnet.json", "chain.json", "assets.json")


def timed(fn):
    wall, cpu = time.monotonic(), time.process_time()
    out = fn()
    return out, round(time.monotonic() - wall, 1), round(time.process_time() - cpu, 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("arena", help="arena directory to copy (read only)")
    p.add_argument("--scratch", required=True, help="scratch directory for the copy (replaced)")
    p.add_argument("--json", help="write the result here")
    a = p.parse_args()
    src, dst = Path(a.arena).expanduser(), Path(a.scratch)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in FILES:
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    out = {"journal_bytes": (dst / "devnet.journal").stat().st_size,
           "journal_records": sum(1 for _ in open(dst / "devnet.journal", "rb"))}
    snapshots = hasattr(devnet.Devnet, "snapshot")
    kw = {}
    if snapshots:
        from qdojo.combat import live
        kw = {"compact": live.compact, "compact_every": live.COMPACT_EVERY}
    net, wall, cpu = timed(lambda: devnet.Devnet(dst, **kw))
    c = net.world.contract
    out["full_replay"] = {"wall_s": wall, "cpu_s": cpu, "tick": net.world.tick,
                          "event_digest": c.event_digest.hex(), "fights_in_memory": len(c.fights),
                          "contests_in_memory": len(c.contests), "offers_in_memory": len(c.offers),
                          "journal_records_in_memory": len(net.world.journal),
                          "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}
    if snapshots:
        path, wall, cpu = timed(net.snapshot)
        out["snapshot_write"] = {"wall_s": wall, "cpu_s": cpu, "bytes": path.stat().st_size}
        del net
        again, wall, cpu = timed(lambda: devnet.Devnet(dst, **kw))
        out["snapshot_restart"] = {"wall_s": wall, "cpu_s": cpu, "mode": again.restart["mode"],
                                   "tried": again.restart["tried"], "tick": again.world.tick,
                                   "event_digest": again.world.contract.event_digest.hex(),
                                   "same_as_full_replay": again.world.contract.event_digest.hex()
                                   == out["full_replay"]["event_digest"]}
    print(json.dumps(out, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
