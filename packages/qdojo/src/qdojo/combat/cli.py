"""`qdojo combat …`: local training, replay verification and evaluation.

None of these commands needs a wallet, NFT, node or seed, and none of them
spends, registers or signs. Chain-backed commands (queue, duel, cup, fighter,
withdraw, bot run) are registered by combat/chain_cli.py.
"""
from __future__ import annotations

import json
import secrets
import shlex
import sys

from . import evaluate as E
from . import npcs, planner
from .rules import candidate_1
from .training import Contestant, explain, run_fight, summary, verify_replay


class CombatCliError(RuntimeError):
    pass


def _seed(text: str | None) -> bytes:
    if text is None:
        return secrets.token_bytes(32)
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        raise CombatCliError("--seed is 64 hex digits") from None
    if len(raw) != 32:
        raise CombatCliError("--seed is 32 bytes (64 hex digits)")
    return raw


def _contestant(name: str, npc: str | None, planner_cmd: str | None, budget: int) -> Contestant:
    if planner_cmd:
        return Contestant(name, command=shlex.split(planner_cmd), budget_ms=budget)
    if npc in npcs.ROSTER:
        return Contestant(name, npc=npc)
    try:
        return Contestant(name, policy=E.policy_by_name(npc), policy_id=npc)
    except KeyError as exc:
        raise CombatCliError(str(exc)) from None


def cmd_npcs(a):
    rows = [{"id": n.id, "behavior": n.behavior, "lesson": n.lesson} for n in npcs.ROSTER.values()]
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        print(f"{r['id']:<11} {r['behavior']}\n{'':<11} lesson: {r['lesson']}")


def cmd_train(a):
    """One free local fight. Without --planner, --as picks which policy you watch."""
    seed = _seed(a.seed)
    you = _contestant("you", a.as_policy, a.planner, a.budget_ms)
    them = _contestant(a.npc, a.npc, None, a.budget_ms)
    replay = run_fight(you, them, seed, a.fight)
    slot = "A" if replay["fighters"]["A"]["name"] == "you" else "B"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(replay, f, indent=1)
    if a.json:
        print(json.dumps({"replay": replay if not a.out else a.out, "you": slot,
                          "summary": summary(replay, slot), "explain": explain(replay, slot),
                          "diagnostics": you.diagnostics}))
        return
    _print_fight(replay, slot)
    s = summary(replay, slot)
    print(f"\nseed {replay['seed']}  (rerun with --seed to reproduce)")
    print(f"exhausted beats {s['exhausted_beats']}, wasted power {s['wasted_power']}, "
          f"punished recoveries {s['recovery_punished']}, blocks thrown {s['guard_broken']}")
    lines = explain(replay, slot)
    if lines:
        print("\nWhere it cost you:")
        for line in lines:
            print("  " + line)
    for d in you.diagnostics:
        if d.get("adjusted"):
            print(f"\nround {d['round_index'] + 1}: your plan was illegal and would forfeit on a chain; "
                  f"{d['adjusted']}")
    for f in replay["fallbacks"]:
        print(f"\nround {f['round_index'] + 1}: your planner failed ({f['cause']}); six RECOVERs were used")
        tail = you.diagnostics[f["round_index"]]["stderr"].strip()
        if tail:
            print("  stderr: " + tail[-400:])


def _print_fight(replay: dict, you: str):
    other = "B" if you == "A" else "A"
    names = {you: "you", other: replay["fighters"][other]["name"]}
    for r in replay["rounds"]:
        print(f"Round {r['round_index'] + 1}")
        for beat in r["beats"]:
            m, t = beat[you], beat[other]
            p = "*" if m["power"] else " "
            print(f"  {beat['beat'] + 1}. you {m['intended']:<7}{p}{'(' + m['effective'] + ')' if m['effective'] != m['intended'] else '':<12}"
                  f" vs {t['intended']:<7}  you {m['after']['hp']:>3}hp {m['after']['stamina']:>2}st"
                  f" | {t['after']['hp']:>3}hp {t['after']['stamina']:>2}st")
        un = r["unexecuted"][you]
        if un:
            print(f"  not played after the knockout: {', '.join(un)}")
    out = replay["outcome"]
    who = "draw" if out["winner"] is None else ("you win" if out["winner"] == you else f"{names[other]} wins")
    print(f"\n{who} ({out['result']})")


def cmd_replay(a):
    with open(a.file, encoding="utf-8") as f:
        replay = json.load(f)
    outcome = verify_replay(replay)
    if a.json:
        print(json.dumps({"verified": True, "outcome": outcome}))
    else:
        print(f"replay re-derived from its plans: {outcome['result']}, winner {outcome['winner'] or 'none (draw)'}")


def cmd_evaluate(a):
    """Side-swapped paired benchmark on seeds separate from training."""
    try:
        policy = E.policy_by_name(a.policy)
    except KeyError as exc:
        raise CombatCliError(str(exc)) from None
    all_pools = E.pools()
    if a.pool not in all_pools:
        raise CombatCliError(f"unknown pool {a.pool!r}; known: {', '.join(all_pools)}")
    pool = all_pools[a.pool]
    if a.opponent:
        pool = {n: E.policy_by_name(n) for n in a.opponent}
    say = (lambda m: print(m, file=sys.stderr)) if not a.json else None
    rows = E.evaluate(policy, pool, a.seeds, suite=a.suite, policy_id=a.policy, progress=say)
    if a.json:
        print(json.dumps({"policy": a.policy, "pool": a.pool, "seeds": a.seeds, "suite": a.suite,
                          "ruleset_digest": candidate_1().digest.hex(), "rows": rows}, indent=1))
    else:
        print(E.markdown(f"{a.policy} vs {a.pool} ({a.seeds} paired seeds, suite {a.suite})", rows))


def add_parser(sub):
    cp = sub.add_parser("combat", help="combat-v1: free training, replays and evaluation (no wallet needed)")
    s = cp.add_subparsers(dest="sub", required=True)

    d = s.add_parser("npcs", help="the disclosed practice opponents")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_npcs)

    d = s.add_parser("train", help="one free local fight against an NPC")
    d.add_argument("--npc", default="random-v1", help="opponent policy (see `qdojo combat npcs`)")
    d.add_argument("--planner", help="your planner command, e.g. 'python3 my_bot.py'")
    d.add_argument("--as", dest="as_policy", default="mixed-v1",
                   help="without --planner, the policy that fights for you")
    d.add_argument("--seed", help="32-byte hex seed; random if omitted and printed so you can rerun")
    d.add_argument("--fight", type=int, default=1, help="fight number within the seed")
    d.add_argument("--budget-ms", type=int, default=planner.DEFAULT_BUDGET_MS)
    d.add_argument("--out", help="write the replay JSON here")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_train)

    d = s.add_parser("replay", help="re-derive a recorded fight from its plans")
    d.add_argument("file")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_replay)

    d = s.add_parser("evaluate", help="batched side-swapped benchmark against a pool")
    d.add_argument("--policy", default="mixed-v1",
                   help="an NPC, search-v1, search-blind, search-nores, or any pool policy")
    d.add_argument("--pool", default="roster")
    d.add_argument("--opponent", action="append", help="evaluate only against these, repeatable")
    d.add_argument("--seeds", type=int, default=100, help="paired seeds per opponent (two fights each)")
    d.add_argument("--suite", default="test", help="seed namespace; keep training and test suites apart")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_evaluate)

    from . import api, chain_cli, join, live
    chain_cli.add_parsers(s)
    live.add_parser(s)
    api.add_parser(s)
    join.add_parser(s)
    return s
