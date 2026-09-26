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
spends settled once their contests finished.

A second, steady-state phase (AUD-025) runs a fresh arena with a normal
reserve and a stand-in for the LLM planners that keeps claiming a spent power
strike. It exports the public data every --export-every ticks and checks the
export against the contract each time (invariants.check_export): no published
live fight overdue, every finished fight published in final form. At the end
no bot may have had a reveal rejected with BAD_PLAN.

Writes a short report.

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

from qdojo.combat import export, invariants, live  # noqa: E402
from qdojo.combat.chainsim import FeeModel  # noqa: E402


def steady(ticks: int, seed: int, export_every: int, drop_rate: float) -> tuple[list[str], dict]:
    """Steady-state phase: exports every `export_every` ticks, each checked
    against the contract; no reveal may be rejected as BAD_PLAN."""
    lineup = [dict(e) for e in live.DEFAULT_LINEUP]
    lineup.append({"label": "ronin", "policy": "mixed-v1", "reliability": 0.3})
    lineup.append({"label": "LLM-STUB", "stub": "power-reuse", "cups": True})
    lineup.append({"label": "LLM-STUB2", "stub": "power-reuse", "duels": True, "ranked": False})
    notes: list[str] = []
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="qdojo-soak-steady-") as tmp:
        arena = live.Arena(Path(tmp) / "arena", lineup, seed=seed + 1, deterministic=True, drop_rate=drop_rate,
                           cup_every=900, duel_every=150, market_every=1500, log=notes.append)
        root = Path(tmp) / "combat" / "v1"
        exports = 0
        for i in range(1, ticks + 1):
            arena.step()
            bad = invariants.check(arena.w)
            if bad:
                problems.append(f"tick {arena.w.tick}: {bad[:3]}")
            if i % export_every == 0:
                export.export_all(arena.w.contract, root, keep=200, deployment=arena.deployment(0))
                exports += 1
                bad = invariants.check_export(arena.w.contract, root, slack=export_every + 1)
                if bad:
                    problems.append(f"export at tick {arena.w.tick}: {bad[:3]}")
            if hasattr(arena, "maintain"):
                arena.maintain()
            if len(problems) > 20:
                break
        rejected = sum((b.rejected for b in arena.bots.values()), collections.Counter())
        if rejected.get("reveal:BAD_PLAN") or rejected.get("commit:BAD_PLAN"):
            problems.append(f"plans rejected as BAD_PLAN: {dict(rejected)}")
        stripped = sum(1 for m in notes if "power_slot dropped" in m)
        if stripped == 0:
            problems.append("the power-reuse stand-in never had a spent power strike stripped; the check was not exercised")
        c = arena.w.contract
        final = sum(1 for p in (root / "fights").glob("*.json") if invariants._read(p).get("final"))
        stats = {"exports": exports, "fights": len(c.fights), "published_final": final,
                 "power_slots_stripped": stripped, "rejections": dict(rejected),
                 "contests": dict(collections.Counter(x.result["kind"] for x in c.contests.values() if x.result))}
    return problems, stats


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticks", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--drop-rate", type=float, default=0.05)
    p.add_argument("--steady-ticks", type=int, default=2000, help="ticks of the steady-state export phase (0: skip)")
    p.add_argument("--export-every", type=int, default=6, help="ticks between exports in the steady phase")
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
    steady_problems = []
    if a.steady_ticks:
        started = time.time()
        steady_problems, stats = steady(a.steady_ticks, a.seed, a.export_every, a.drop_rate)
        report += ["", "## Steady state with exports (AUD-025)", "",
                   f"{a.steady_ticks} ticks, export every {a.export_every} ticks; runtime {time.time() - started:.0f} s.", "",
                   f"- Exports checked: {stats['exports']}; fights {stats['fights']}, published final {stats['published_final']}",
                   f"- Contests: {stats['contests']}",
                   f"- Spent power slots stripped before commit: {stats['power_slots_stripped']}; "
                   f"final commit/reveal rejections: {stats['rejections'] or 'none'}",
                   f"- Problems: {len(steady_problems)}"]
        report += [f"  - {x}" for x in steady_problems[:10]]
    text = "\n".join(report) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text)
    sys.exit(1 if violations or unsettled or steady_problems else 0)


if __name__ == "__main__":
    main()
