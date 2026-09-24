#!/usr/bin/env python3
"""Soak run: a long simulated arena season with invariants checked every tick.

Runs the demo arena on the simulated chain for a lineup with some churn:
- a flaky bot that forfeits now and then;
- NFT sales to collectors;
- cups and duels;
- drops and fee halts: a small reserve that runs dry, is topped up late, and
  causes service gaps.

After every tick it checks conservation, lock integrity and liveness
(combat/invariants.py). At the end it also checks that every bot's budget
spends settled once their contests finished. Writes a short report.

  uv run python scripts/combat-soak.py --ticks 20000 --out soak-report.md
Exit status 1 on any violation.
"""
from __future__ import annotations

import argparse
import collections
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import invariants, live  # noqa: E402
from qdojo.combat.chainsim import FeeModel  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticks", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--drop-rate", type=float, default=0.05)
    p.add_argument("--out", help="write a markdown report here")
    a = p.parse_args()
    lineup = [{**e, "founding": e["label"] in ("tanuki", "tengu")} for e in live.DEFAULT_LINEUP]
    lineup.append({"label": "ronin", "policy": "mixed-v1", "reliability": 0.06})
    started = time.time()
    violations = []
    with tempfile.TemporaryDirectory(prefix="qdojo-soak-") as tmp:
        arena = live.Arena(Path(tmp) / "arena", lineup, seed=a.seed, deterministic=True,
                           drop_rate=a.drop_rate, fees=FeeModel(per_call=5, per_tick=1, per_resolved_round=10),
                           cup_every=1500, market_every=2000, log=lambda m: None)
        # A thin reserve so the contract halts now and then (service gaps), topped up late.
        arena.chain.reserve = 3000
        floor = live.RESERVE_FLOOR
        live.RESERVE_FLOOR = -1                         # disable the automatic top-up
        try:
            for i in range(a.ticks):
                arena.step()
                if arena.chain.reserve is not None and arena.chain.reserve < 5 and i % 700 == 0:
                    arena.chain.fund_reserve(4000)      # the operator notices late
                bad = invariants.check(arena.w)
                if bad:
                    violations.append((arena.w.tick, bad))
                    if len(violations) > 20:
                        break
        finally:
            live.RESERVE_FLOOR = floor
        c = arena.w.contract
        # Spends of finished contests must have settled in every bot's budget.
        unsettled = 0
        for b in arena.bots.values():
            b._settle_known()
            for s in b.bstate.spends:
                if s.returned is None and s.contest_or_offer.startswith("contest:"):
                    ct = c.contests.get(int(s.contest_or_offer.split(":")[1]))
                    if ct is not None and ct.status == "DONE":
                        unsettled += 1
        kinds = collections.Counter(x.result["kind"] for x in c.contests.values() if x.result)
        cups = collections.Counter(k.status for k in c.cups.values())
        report = [
            "# Combat soak run", "",
            f"{a.ticks} ticks, seed {a.seed}, drop rate {a.drop_rate}, {len(arena.bots)} bots; "
            f"runtime {time.time() - started:.0f} s.", "",
            f"- Contests: {dict(kinds)}",
            f"- Cups: {dict(cups)}; duels: {sum(1 for x in c.contests.values() if x.mode == 1)}",
            f"- NFT sales: {arena.state['collectors']}; contract service generation: {c.generation} "
            f"(halted ticks {arena.chain.halted_ticks})",
            f"- Transactions: {len(arena.chain.txs)}, dropped "
            f"{sum(1 for t in arena.chain.txs.values() if t.status == 'dropped')}",
            f"- Invariant violations: {len(violations)}",
            f"- Finished contests with an unsettled bot budget: {unsettled}",
        ]
        for tick, bad in violations[:10]:
            report.append(f"  - tick {tick}: {bad[:3]}")
    text = "\n".join(report) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text)
    sys.exit(1 if violations or unsettled else 0)


if __name__ == "__main__":
    main()
