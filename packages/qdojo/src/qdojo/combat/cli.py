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
from .rules import KNOWN, PUBLIC_ARENA, by_version
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


def _contestant(name: str, npc: str | None, planner_cmd: str | None, budget: int, rules=None) -> Contestant:
    if planner_cmd:
        return Contestant(name, command=shlex.split(planner_cmd), budget_ms=budget)
    if npc in npcs.ROSTER:
        return Contestant(name, npc=npc)
    try:
        return Contestant(name, policy=E.policy_by_name(npc, rules), policy_id=npc)
    except KeyError as exc:
        raise CombatCliError(str(exc)) from None


def cmd_npcs(a):
    rows = [{"id": n.id, "behavior": n.behavior, "lesson": n.lesson} for n in npcs.ROSTER.values()]
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        print(f"{r['id']:<11} {r['behavior']}\n{'':<11} lesson: {r['lesson']}")


def ruleset_line(rules) -> str:
    """Printed before any result: which rules produced it."""
    note = "the public arena's rules" if rules.semantic_version == PUBLIC_ARENA else \
        f"NOT the public arena's rules ({PUBLIC_ARENA})"
    return f"ruleset {rules.semantic_version} {rules.digest.hex()[:16]} ({note})"


def cmd_train(a):
    """One free local fight. Without --planner, --as picks which policy you watch."""
    seed = _seed(a.seed)
    rules = by_version(a.ruleset)
    you = _contestant("you", a.as_policy, a.planner, a.budget_ms, rules)
    them = _contestant(a.npc, a.npc, None, a.budget_ms, rules)
    if not a.json:
        print(ruleset_line(rules))
    replay = run_fight(you, them, seed, a.fight, rules)
    slot = "A" if replay["fighters"]["A"]["name"] == "you" else "B"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(replay, f, indent=1)
    if a.json:
        print(json.dumps({"ruleset_digest": rules.digest.hex(), "semantic_version": rules.semantic_version,
                          "replay": replay if not a.out else a.out, "you": slot,
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
    """A practice replay (from train --out) or an arena replay (an export's
    fights/<id>/replay.json, a file or an http(s) URL)."""
    from . import replaycheck
    try:
        replay = replaycheck.load(a.file)
    except (OSError, ValueError) as exc:
        raise CombatCliError(f"cannot read {a.file}: {exc}") from None
    try:
        if replaycheck.is_arena(replay):
            report = replaycheck.verify_arena_replay(replay)
            outcome, kind = report["outcome"], "arena"
        else:
            outcome, kind, report = verify_replay(replay), "practice", None
    except replaycheck.ReplayMismatch as exc:
        if a.json:
            print(json.dumps({"verified": False, "error": str(exc)}))
        else:
            print(f"replay FAILED verification: {exc}")
        sys.exit(1)
    if a.json:
        print(json.dumps({"verified": True, "kind": kind, "ruleset_digest": replay.get("ruleset_digest"),
                          "outcome": outcome, **({"checks": report["checks"]} if report else {})}))
        return
    print(f"ruleset {replay.get('semantic_version', '?')} {str(replay.get('ruleset_digest'))[:16]}")
    if report:
        for line in report["checks"]:
            print("  " + line)
    if outcome is None:
        print(f"{kind} replay verified so far; the fight has no result yet")
    else:
        print(f"{kind} replay re-derived from its plans: {outcome['result']}, "
              f"winner {outcome['winner'] or 'none (draw)'}")


def cmd_evaluate(a):
    """Side-swapped paired benchmark on seeds separate from training."""
    rules = by_version(a.ruleset)
    all_pools = E.pools(rules)
    pool_name = a.pool or ("builder" if a.planner else "roster")
    if pool_name not in all_pools:
        raise CombatCliError(f"unknown pool {pool_name!r}; known: {', '.join(all_pools)}")
    pool = all_pools[pool_name]
    if a.opponent:
        try:
            pool = {n: E.policy_by_name(n, rules) for n in a.opponent}
        except KeyError as exc:
            raise CombatCliError(str(exc)) from None
        pool_name = "custom"
    if a.planner:
        return _evaluate_planners(a, rules, pool_name, pool)
    seeds = a.seeds if a.seeds is not None else 100
    try:
        policy = E.policy_by_name(a.policy, rules)
    except KeyError as exc:
        raise CombatCliError(str(exc)) from None
    a.pool, a.seeds = pool_name, seeds
    say = (lambda m: print(m, file=sys.stderr)) if not a.json else None
    rows = E.evaluate(policy, pool, a.seeds, suite=a.suite, policy_id=a.policy, progress=say, rules=rules)
    if a.json:
        print(json.dumps({"policy": a.policy, "pool": a.pool, "seeds": a.seeds, "suite": a.suite,
                          "ruleset_digest": rules.digest.hex(), "semantic_version": rules.semantic_version,
                          "rows": rows}, indent=1))
    else:
        print(E.markdown(f"{a.policy} vs {a.pool} ({a.seeds} paired seeds, suite {a.suite}, "
                         f"{rules.semantic_version} {rules.digest.hex()[:16]})", rows))


def _evaluate_planners(a, rules, pool_name, pool):
    """`evaluate --planner CMD [--planner CMD2 ...]`: each command on the same
    seeds and opponents; with two or more, paired differences against the first.
    Exits 1 if any round fell back because a planner failed."""
    seeds = a.seeds if a.seeds is not None else 20
    say = (lambda m: print(m, file=sys.stderr)) if not a.json else None
    head = (f"{ruleset_line(rules)}\npool {pool_name}: {len(pool)} opponents ({', '.join(pool)})\n"
            f"seed suite {a.suite!r}: {seeds} paired seeds per opponent, each fought twice with sides swapped")
    if say:
        say(head)
    results = []
    for text in a.planner:
        cmd = shlex.split(text)
        if say:
            say(f"planner: {text}")
        results.append(E.evaluate_planner(cmd, pool, seeds, a.suite, rules, a.budget_ms, say))
    comparisons = [E.compare(results[0], r) for r in results[1:]]
    failed = [r for r in results if r["planner"]["fallback_rounds"]]
    if a.json:
        print(json.dumps({"schema": "qdojo.combat.evaluation.v1", "ruleset_digest": rules.digest.hex(),
                          "semantic_version": rules.semantic_version, "pool": pool_name,
                          "opponents": list(pool), "seeds": seeds, "suite": a.suite,
                          "fights_per_opponent": 2 * seeds, "budget_ms": a.budget_ms,
                          "planners": [{k: v for k, v in r.items() if k != "pair_scores"} for r in results],
                          "comparisons": comparisons}, indent=1))
    else:
        print(head)
        for r in results:
            p = r["planner"]
            print()
            print(E.planner_markdown(f"{' '.join(r['command'])} vs {pool_name}", r))
            print(f"planner rounds {p['rounds']}: {p['rounds'] - p['fallback_rounds']} ran, "
                  f"{p['fallback_rounds']} fell back to six RECOVERs"
                  + (f" ({', '.join(f'{k} {v}' for k, v in p['failures'].items())}) in "
                     f"{p['fights_with_fallback']} of {p['fights']} fights" if p["fallback_rounds"] else "")
                  + f"; {p['adjusted_rounds']} adjusted (spent power slot dropped or illegal plan replaced); "
                  f"slowest {p['max_ms']} ms")
            if p["first_error"]:
                print(f"first failure: {p['first_error']}")
        for c in comparisons:
            print(f"\n{' '.join(c['other'])} minus {' '.join(c['base'])}: {c['mean_difference']:+.3f} per pair "
                  f"(95% interval {c['lower95']:+.3f} to {c['upper95']:+.3f}, {c['pairs']} pairs on identical seeds)")
    if failed:
        sys.stdout.flush()
        print(f"qdojo: {len(failed)} planner(s) failed in some rounds; those rounds used the fallback plan, "
              f"so their fights are not the planner's play (see fallback rounds above)", file=sys.stderr)
        sys.exit(1)


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
    d.add_argument("--ruleset", default=PUBLIC_ARENA, choices=tuple(KNOWN),
                   help="packaged ruleset to fight under (default: %(default)s, the public arena's)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_train)

    d = s.add_parser("replay", help="re-derive a recorded fight from its plans")
    d.add_argument("file", help="a practice replay (train --out) or an arena replay.json: a path or an http(s) URL")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_replay)

    d = s.add_parser("evaluate", help="batched side-swapped benchmark against a pool")
    d.add_argument("--planner", action="append",
                   help="your planner command, e.g. 'python3 my_bot.py'; repeat to compare versions on the same seeds")
    d.add_argument("--policy", default="mixed-v1",
                   help="without --planner: an NPC, search-v1, search-blind, search-nores, or any pool policy")
    d.add_argument("--pool", help="opponent pool: roster, house, builder, baseline, ... "
                                  "(default: builder with --planner, else roster)")
    d.add_argument("--opponent", action="append", help="evaluate only against these, repeatable")
    d.add_argument("--seeds", type=int, help="paired seeds per opponent, two fights each "
                                             "(default: 20 with --planner, else 100)")
    d.add_argument("--suite", default="test", help="seed namespace; tune on one (e.g. train), report another")
    d.add_argument("--budget-ms", type=int, default=planner.DEFAULT_BUDGET_MS, help="with --planner: time per round")
    d.add_argument("--ruleset", default=PUBLIC_ARENA, choices=tuple(KNOWN),
                   help="packaged ruleset to fight under (default: %(default)s, the public arena's)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_evaluate)

    from . import api, chain_cli, join, live, nft_freeze, nft_qbay
    chain_cli.add_parsers(s)
    live.add_parser(s)
    api.add_parser(s)
    join.add_parser(s)
    nft_freeze.add_parser(s)
    nft_qbay.add_parser(s)
    return s
