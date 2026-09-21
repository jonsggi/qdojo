#!/usr/bin/env python3
"""Measure the Qubic riddle pack on fresh instances (Refs #17).

Everything here runs offline: instances come from the generator at rng
seeds far from the published practice seeds (7 and 3) and from the test
sweeps (0..299), solvers run through solver.run_solver (the path `bot run`
uses), and the sparring rounds run on FakeChain, the way
test_qubic_riddles.py drives one. Nothing signs or broadcasts.

    uv run python scripts/riddle-pack-measure.py all
    uv run python scripts/riddle-pack-measure.py solve --n 200
    uv run python scripts/riddle-pack-measure.py reuse --first-look-only
    uv run python scripts/riddle-pack-measure.py spar

`solve` runs the shipped solvers and the weak floors over N fresh instances
and reports solve rate, wall latency, and input size. `reuse` runs the
frozen first-look solvers in scripts/riddle-pack/first-look/ (written
against one instance, never edited) and the shipped ones over the same 50
fresh instances. `spar` fights one fake-chain round per family with three
bots, once staggered and once in lockstep, to show what payout_mode first
does with each. Output is Markdown; --json also writes the raw rows.
"""
import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time

from qdojo import riddle as R
from qdojo import riddles
from qdojo.solver import SolverError, run_solver

FAMILIES = {
    "qubic_transaction_audit": "orange",
    "qubic_asset_ledger": "green",
    "qubic_call_audit": "blue",
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLVERS = os.path.join(ROOT, "examples", "solvers")
FIRST_LOOK = os.path.join(ROOT, "scripts", "riddle-pack", "first-look")
FLOORS = ("bare.py", "echo.py")
INSTANCE_A = 1900001          # the one instance the first-look solvers saw
SOLVER_TIMEOUT = 60.0         # the shipped --solver-timeout default (bot run, train)
NOOP = [sys.executable, "-c", "import sys; sys.stdin.read(); print('{\"answer\": 0}')"]


def instances(kind, base, n):
    return [riddles.generate_kind(kind, random.Random(base + i), 1) for i in range(n)]


def public(doc):
    return R.from_public(doc).public()


def attempt(cmd, doc, timeout=SOLVER_TIMEOUT):
    """One solve through the bot's own path. Returns (answer or None, error, seconds)."""
    t0 = time.perf_counter()
    try:
        return run_solver(cmd, public(doc), timeout), "", time.perf_counter() - t0
    except SolverError as e:
        return None, str(e), time.perf_counter() - t0


def stats(xs):
    xs = sorted(xs)
    if not xs:
        return "-"
    p95 = xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]
    return f"{xs[0]:.3f} / {statistics.median(xs):.3f} / {p95:.3f} / {xs[-1]:.3f}"


def size_stats(xs):
    xs = sorted(xs)
    return f"{xs[0]} / {int(statistics.median(xs))} / {xs[-1]}"


def measure(cmd, docs, base, timeout=SOLVER_TIMEOUT):
    out = {"solved": 0, "misses": [], "seconds": []}
    for i, doc in enumerate(docs):
        ans, err, sec = attempt(cmd, doc, timeout)
        out["seconds"].append(sec)
        if ans == str(doc["answer"]):
            out["solved"] += 1
        else:
            out["misses"].append({"seed": base + i, "truth": doc["answer"], "answer": ans, "error": err[:200]})
    return out


def variant(kind, doc):
    """The query shape a solver written against one instance has seen."""
    data = json.loads(doc["input"])
    q = data["query"]
    if kind == "qubic_transaction_audit":
        width = q["tick_max"] - q["tick_min"]
        return (q["metric"], "source" in q, "width0" if width == 0 else "width>0")
    if kind == "qubic_asset_ledger":
        return (data["settled"], q["role"], q["manager"] is not None)
    return (q["metric"], q["identity"].startswith("C"))


# ------------------------------------------------------------------ solve

def cmd_solve(a):
    print(f"## Solve rate, latency and size over {a.n} fresh instances (rng seeds {a.base}..{a.base + a.n - 1})\n")
    print("Latency is wall time through solver.run_solver on a shared 2-CPU box: min / median / p95 / max seconds. "
          f"The spawn floor row is a solver that prints 0 without reading the riddle. The shipped --solver-timeout is {SOLVER_TIMEOUT:.0f} s.\n")
    rows = {}
    for kind, belt in FAMILIES.items():
        docs = instances(kind, a.base, a.n)
        inputs = [len(d["input"].encode()) for d in docs]
        stdin = [len(json.dumps(public(d)).encode()) for d in docs]
        zeros = sum(1 for d in docs if d["answer"] == 0)
        shipped = measure([sys.executable, os.path.join(SOLVERS, kind + ".py")], docs, a.base)
        floor = measure(NOOP, docs, a.base)
        weak = {f: measure([sys.executable, os.path.join(SOLVERS, f)], docs, a.base) for f in FLOORS}
        rows[kind] = {"belt": belt, "n": a.n, "zeros": zeros, "input_bytes": inputs, "stdin_bytes": stdin,
                      "shipped": shipped, "spawn_floor": floor, "weak": weak}
        print(f"### {kind} ({belt})\n")
        print("| measure | value |\n|---|---|")
        print(f"| input field bytes min / median / max | {size_stats(inputs)} |")
        print(f"| stdin bytes (public JSON, statement included) min / median / max | {size_stats(stdin)} |")
        print(f"| answers equal to zero | {zeros} / {a.n} |")
        print(f"| shipped `{kind}.py` solved | {shipped['solved']} / {a.n} |")
        print(f"| shipped latency s | {stats(shipped['seconds'])} |")
        print(f"| spawn floor latency s | {stats(floor['seconds'])} |")
        print(f"| shipped max latency vs {SOLVER_TIMEOUT:.0f} s timeout | {max(shipped['seconds']) / SOLVER_TIMEOUT * 100:.2f} % |")
        for f, m in weak.items():
            hits = [i for i in range(a.n) if i not in {miss["seed"] - a.base for miss in m["misses"]}]
            by_zero = sum(1 for i in hits if docs[i]["answer"] == 0)
            print(f"| floor `{f}` solved | {m['solved']} / {a.n} ({by_zero} of them zero answers) |")
        print()
        if shipped["misses"]:
            print("Misses (each is a finding about the statement or the generator):\n")
            for miss in shipped["misses"]:
                print(f"- seed {miss['seed']}: truth {miss['truth']}, answered {miss['answer']!r} {miss['error']}")
            print()
    return rows


# ------------------------------------------------------------------ reuse

def cmd_reuse(a):
    print(f"## Tool reuse: a solver written against one instance, run unchanged on {a.reuse_n} fresh ones "
          f"(rng seeds {a.reuse_base}..{a.reuse_base + a.reuse_n - 1})\n")
    print(f"The first-look solvers in scripts/riddle-pack/first-look/ were written from the statement while looking "
          f"only at rng seed {INSTANCE_A}, then frozen. The variant column is the query shape of that one instance and "
          f"how many of the fresh instances share it.\n")
    rows = {}
    print("| family | instance A variant | fresh sharing it | first-look survived | shipped solved |\n|---|---|---|---|---|")
    for kind, belt in FAMILIES.items():
        docs = instances(kind, a.reuse_base, a.reuse_n)
        seen = variant(kind, riddles.generate_kind(kind, random.Random(INSTANCE_A), 1))
        share = sum(1 for d in docs if variant(kind, d) == seen)
        first = measure([sys.executable, os.path.join(FIRST_LOOK, kind + ".py")], docs, a.reuse_base)
        shipped = None
        if not a.first_look_only:
            shipped = measure([sys.executable, os.path.join(SOLVERS, kind + ".py")], docs, a.reuse_base)
        rows[kind] = {"variant": seen, "share": share, "first_look": first, "shipped": shipped}
        print(f"| {kind} | {seen} | {share} / {a.reuse_n} | {first['solved']} / {a.reuse_n} | "
              f"{'-' if shipped is None else str(shipped['solved']) + ' / ' + str(a.reuse_n)} |")
    print()
    for kind, r in rows.items():
        for label in ("first_look", "shipped"):
            m = r[label]
            if m and m["misses"]:
                print(f"{kind} {label} misses:\n")
                for miss in m["misses"]:
                    print(f"- seed {miss['seed']}: truth {miss['truth']}, answered {miss['answer']!r} {miss['error']}")
                print()
    return rows


# ------------------------------------------------------------------ spar

HOUSE = "H" * 60
FIGHTERS = {"fast": "A" * 60, "slow": "B" * 60, "floor": "C" * 60, "twin": "D" * 60}


class View:
    """A signing view over one shared FakeChain: same ticks, own identity.
    Mirrors the World/View pair in packages/qdojo/tests/test_house_and_bot.py."""

    def __init__(self, core, identity):
        self.core, self.identity = core, identity

    def current_tick(self):
        return self.core.current_tick()

    def indexed_tick(self):
        return self.core.indexed_tick()

    def balance(self, i):
        return self.core.balance(i)

    def confirm(self, tx, tick):
        return self.core.confirm(tx, tick)

    def transactions_to(self, i, lo, hi):
        return self.core.transactions_to(i, lo, hi)

    def send(self, dest, amount, payload=b"", input_type=0):
        saved = self.core.identity
        self.core.identity = self.identity
        try:
            return self.core.send(dest, amount, payload, input_type)
        finally:
            self.core.identity = saved


def spar_round(kind, belt, lineup, seed):
    """One round on FakeChain. `lineup` is [(name, solver_cmd, delay_ticks)]:
    a bot first polls the board `delay_ticks` after the riddle is visible and
    every tick after that, which is the fake-chain form of a staggered
    --interval or a slower solver."""
    from qdojo import spar as SP
    from qdojo.bot import Bot
    from qdojo.chain import FakeChain
    from qdojo.house import House

    core = FakeChain(identity=HOUSE, tick=1000,
                     balances={HOUSE: 100_000, **{FIGHTERS[n]: 5_000 for n, _, _ in lineup}})
    with tempfile.TemporaryDirectory() as tmp:
        house = House(View(core, HOUSE), os.path.join(tmp, "house"), HOUSE, rake_bps=500, seed_per_round=1000)
        orig = house.chain.confirm

        def confirm_advancing(tx, tick):
            if core.tick < tick:
                core.advance(tick - core.tick)
            return orig(tx, tick)
        house.chain.confirm = confirm_advancing

        bots = []
        for name, cmd, delay in lineup:
            bot = Bot(View(core, FIGHTERS[name]), os.path.join(tmp, "bot-" + name), cmd, name=name)
            bot.house = HOUSE
            bot.bow()
            bots.append([bot, delay, None])
        board_path = os.path.join(tmp, "web", "board.json")
        actions = []

        def advance(_):
            core.advance(1)
            if not os.path.exists(board_path):
                return
            with open(board_path) as f:
                board = json.load(f)
            visible = any(rd.get("riddle") for rd in board.get("rounds", []))
            for entry in bots:
                bot, delay, seen = entry
                if visible and seen is None:
                    entry[2] = seen = core.tick
                if seen is None or core.tick < seen + delay:
                    continue
                for line in bot.step(board):
                    actions.append((core.tick, bot.name, line))

        class SparTime:
            sleep = staticmethod(advance)

            def __getattr__(self, name):
                return getattr(time, name)

        saved = SP.time
        SP.time = SparTime()
        try:
            runner = SP.Spar(house, [belt], 1000, 50, 20, os.path.join(tmp, "riddles"), os.path.join(tmp, "web"),
                             os.path.join(tmp, "metrics.jsonl"), seed=seed, poll=0, riddle_pack="qubic")
            row = runner.one_round(belt)
        finally:
            SP.time = saved
        assert row["kind"] == kind and row["settled"], row
        return row, actions


def cmd_spar(a):
    print("## Fake-chain sparring rounds (payout_mode first, entry fee 1000, commit window 50 ticks, reveal 20)\n")
    print("Bots poll the board through Bot.step on a shared FakeChain; a delay of d ticks means the bot first sees the "
          "riddle d ticks after publication and every tick after that. Solvers run through solver.run_solver, the real "
          "path. Latency is commit_tick minus publish_tick (the fake chain schedules a send 5 ticks ahead).\n")
    rows = {}
    for i, (kind, belt) in enumerate(FAMILIES.items()):
        shipped = [sys.executable, os.path.join(SOLVERS, kind + ".py")]
        bare = [sys.executable, os.path.join(SOLVERS, "bare.py")]
        lineups = {
            "staggered": [("fast", shipped, 0), ("slow", shipped, 3), ("floor", bare, 0)],
            "lockstep": [("fast", shipped, 0), ("twin", shipped, 0), ("floor", bare, 0)],
        }
        rows[kind] = {}
        for label, lineup in lineups.items():
            row, actions = spar_round(kind, belt, lineup, a.spar_seed + i)
            rows[kind][label] = row
            print(f"### {kind} ({belt}), {label}\n")
            print(f"round {row['round_id']} `{row['title']}` pot {row['pot']} solved {row['n_solved']}/{row['n_entries']}\n")
            print("| fighter | delay | verdict | commit latency ticks | reveal latency ticks | answer | paid |\n|---|---|---|---|---|---|---|")
            paid = {p["identity"]: p["amount"] for p in row["payouts"] if p["kind"] == "win"}
            delays = {n: d for n, _, d in lineup}
            for e in row["entries"]:
                print(f"| {e['name']} | {delays[e['name']]} | {e['verdict']} | {e['commit_latency_ticks']} | "
                      f"{e['reveal_latency_ticks']} | {e['answer']} | {paid.get(e['identity'], 0)} |")
            print()
    return rows


# ------------------------------------------------------------------ main

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("what", choices=("solve", "reuse", "spar", "all"))
    p.add_argument("--n", type=int, default=200, help="fresh instances per family for solve")
    p.add_argument("--base", type=int, default=1_700_000, help="first rng seed for solve")
    p.add_argument("--reuse-n", type=int, default=50)
    p.add_argument("--reuse-base", type=int, default=1_800_000)
    p.add_argument("--spar-seed", type=int, default=1_950_000)
    p.add_argument("--first-look-only", action="store_true", help="reuse: skip the shipped solvers")
    p.add_argument("--json", help="also write the raw rows here")
    a = p.parse_args(argv)
    out = {}
    if a.what in ("solve", "all"):
        out["solve"] = cmd_solve(a)
    if a.what in ("reuse", "all"):
        out["reuse"] = cmd_reuse(a)
    if a.what in ("spar", "all"):
        out["spar"] = cmd_spar(a)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
