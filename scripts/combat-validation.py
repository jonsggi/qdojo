#!/usr/bin/env python3
"""Run the docs/model.md §2 strategic campaign for a ruleset and write a report.

Every gate is evaluated and printed PASS or FAIL with its numbers; failures
are reported, never dropped. Test seeds (suite "test/...") are disjoint from
the "train/..." seeds used while developing the instruments, and the pools
include withheld parameter variants.

  uv run python scripts/combat-validation.py --seeds 1000 --out docs/validation-report.md
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import evaluate as E  # noqa: E402
from qdojo.combat import npcs  # noqa: E402
from qdojo.combat.engine import resolve_round  # noqa: E402
from qdojo.combat.rules import CANDIDATE_1, KNOWN, by_version  # noqa: E402
from qdojo.combat.types import FightState  # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def gate(name, ok, detail):
    return {"gate": name, "pass": bool(ok), "detail": detail}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seeds", type=int, default=1000, help="paired seeds per matchup for cheap policies (fights = 2x)")
    p.add_argument("--costly-seeds", type=int, default=250, help="paired seeds for search/reader planners")
    p.add_argument("--search-candidates", type=int, default=60)
    p.add_argument("--search-samples", type=int, default=8)
    p.add_argument("--out", default=str(ROOT / "docs/validation-report.md"))
    p.add_argument("--suite", default="test", help="seed namespace; use a fresh one after any instrument change")
    p.add_argument("--ruleset", default=CANDIDATE_1, choices=tuple(KNOWN), help="packaged ruleset to validate")
    a = p.parse_args()
    rules = by_version(a.ruleset)
    pools = E.pools(rules)
    search = E.SearchPlanner(candidates=a.search_candidates, samples=a.search_samples)
    reader = E.ReaderPlanner()
    started = time.time()
    # The code under test is what was loaded now, so record the commit now, not at the end.
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    gates, sections, raw = [], [], {}

    # 1. Baselines and obvious exploits: every simple strategy needs a practical counter.
    #    Cheap counters first; the known-policy best response (a published or scouted
    #    style) and the reader are tried only when those fall short.
    simple = {k: v for k, v in pools["baseline"].items() if k not in ("mixed-v1", "scout-v1", "random-v1")}
    rows, missing = [], []
    for name, pol in simple.items():
        log(f"counter search for {name}")
        best = None
        tiers = [{"scout-v1": npcs.scout_v1, "mixed-v1": npcs.mixed_v1},
                 {"known-policy-response": E.KnownPolicyResponse(pol)},
                 {"reader-v1": reader}]
        for tier in tiers:
            for cname, cpol in tier.items():
                seeds = a.seeds if cname in ("scout-v1", "mixed-v1", "known-policy-response") else a.costly_seeds * 4
                r = E.summarize(name, E.paired(cpol, pol, seeds, f"{a.suite}/counter/{name}", rules=rules))
                r["counter"] = cname
                if best is None or r["lower95"] > best["lower95"]:
                    best = r
            if best["score"] >= 0.60 and best["lower95"] > 0.55 and best["fights"] >= 2000:
                break
        rows.append(best)
        if not (best["score"] >= 0.60 and best["lower95"] > 0.55 and best["fights"] >= 2000):
            missing.append(name)
    raw["counters"] = rows
    gates.append(gate("Every simple strategy has a practical counter (>=0.60, LB>0.55, >=2000 fights)", not missing,
                      f"{len(rows) - len(missing)}/{len(rows)} countered"
                      + (f"; uncountered: {', '.join(missing)}" if missing else "")))
    sections.append("### Best counter per simple strategy\n\n| Strategy | Counter | Score | 95% LB | Fights |\n"
                    "|---|---|---:|---:|---:|\n" + "\n".join(
                        f"| {r['opponent']} | {r['counter']} | {r['score']:.3f} | {r['lower95']:.3f} | {r['fights']} |"
                        for r in rows) + "\n")

    # 2. Optimization reward.
    log("optimization reward")
    planners = {"scout-v1": (npcs.scout_v1, a.seeds), "search-v1": (search, a.costly_seeds * 4),
                "reader-v1": (reader, a.costly_seeds * 4)}
    reward = {}
    for pname, (pol, seeds) in planners.items():
        vs_random = E.summarize("random-v1", E.paired(pol, npcs.random_v1, seeds, f"{a.suite}/reward/random", rules=rules))
        style_scores = []
        per = max(1, -(-seeds // len(pools["fixed-style"])))
        for oname, opol in pools["fixed-style"].items():
            style_scores += E.paired(pol, opol, per, f"{a.suite}/reward/{oname}", rules=rules).scores
        style = {"score": E.mean(style_scores), "lower95": E.bootstrap_lower(style_scores),
                 "fights": 2 * len(style_scores)}
        reward[pname] = {"random": vs_random, "fixed_style": style}
    raw["reward"] = reward

    def rewarded(v):
        return (v["random"]["score"] >= 0.65 and v["random"]["lower95"] > 0.60 and v["random"]["fights"] >= 2000
                and v["fixed_style"]["score"] >= 0.60 and v["fixed_style"]["lower95"] > 0.55
                and v["fixed_style"]["fights"] >= 2000)
    gates.append(gate("A <=1500 ms planner beats random (>=0.65, LB>0.60) and fixed styles (>=0.60, LB>0.55), "
                      ">=2000 fights each", any(rewarded(v) for v in reward.values()),
                      "; ".join(f"{k}: random {v['random']['score']:.3f} (LB {v['random']['lower95']:.3f}, "
                                f"{v['random']['fights']}), styles {v['fixed_style']['score']:.3f} "
                                f"(LB {v['fixed_style']['lower95']:.3f}, {v['fixed_style']['fights']})"
                                for k, v in reward.items())))

    # 3. Ablations of the reader on the predictable pool (fixed styles + strong scripts).
    log("ablations")
    pred = pools["predictable"]
    per = max(1, a.costly_seeds // len(pred))
    res_ab = E.ablation(reader, E.ReaderPlanner(ignore_resources=True), pred, per, f"{a.suite}/ablation/resources", rules=rules)
    hist_ab = E.ablation(reader, E.ReaderPlanner(use_history=False), pred, per, f"{a.suite}/ablation/history", rules=rules)
    raw["ablation"] = {"resources": res_ab, "history": hist_ab}
    gates.append(gate("Resource/opening state matters to the improved planner (>=0.05, LB>0)",
                      res_ab["mean_improvement"] >= 0.05 and res_ab["lower95"] > 0,
                      f"reader-v1 vs its no-resource ablation: +{res_ab['mean_improvement']:.3f} "
                      f"(LB {res_ab['lower95']:.3f}, {res_ab['pairs']} pairs)"))
    gates.append(gate("History-aware beats history-blind on predictable families (>=0.05, LB>0)",
                      hist_ab["mean_improvement"] >= 0.05 and hist_ab["lower95"] > 0,
                      f"reader-v1 vs history-blind: +{hist_ab['mean_improvement']:.3f} "
                      f"(LB {hist_ab['lower95']:.3f}, {hist_ab['pairs']} pairs)"))

    # 4. Same round-start state, different beliefs: do several competitive plans occur?
    log("plan diversity")
    s0 = FightState(1, npcs.FighterState(70, 40, 0, 0, 1), npcs.FighterState(70, 40, 0, 0, 1))
    beliefs = {name: E.KnownPolicyResponse(pol, samples=2) for name, pol in pools["predictable"].items()}
    plans = {}
    for name, br in beliefs.items():
        obs = npcs.Observation(1, s0.a, s0.b, (), "A", ())
        plans[name] = br(rules, obs, npcs.Stream(bytes(32), 1, 1))
    distinct = {pl.actions for pl in plans.values()}
    # "Competitive": each plan beats at least one belief's predicted opponent.
    competitive = set()
    for name, pl in plans.items():
        for oname, opol in pools["predictable"].items():
            oplan = opol(rules, npcs.Observation(1, s0.b, s0.a, (), "B", ()), npcs.Stream(bytes(32), 1, 1))
            end = resolve_round(rules, s0, pl, oplan).end
            if end.a.hp > end.b.hp:
                competitive.add(pl.actions)
                break
    raw["diversity"] = {"distinct_plans": len(distinct), "competitive": len(competitive)}
    gates.append(gate("Same state, different beliefs: >=2 competitive plans", len(competitive) >= 2,
                      f"{len(distinct)} distinct plans from {len(beliefs)} beliefs; {len(competitive)} competitive"))

    # 5. Fight shape on the competent pool (round robin, excluding passive NPCs).
    log("fight shape")
    competent = {"mixed-v1": npcs.mixed_v1, "scout-v1": npcs.scout_v1, "repeat-last-winner": E.repeat_last_winner,
                 "search-v1": search, "reader-v1": reader}
    costly = {"search-v1", "reader-v1"}
    names = list(competent)
    total = E.Tally()
    strength = {n: [] for n in names}
    matrix = []
    for i, x in enumerate(names):
        for y in names[i:]:
            seeds = a.costly_seeds if {x, y} & costly else a.seeds
            t = E.paired(competent[x], competent[y], seeds, f"{a.suite}/shape/{x}/{y}", rules=rules)
            matrix.append(E.summarize(f"{x} vs {y}", t))
            strength[x] += t.scores
            if x != y:
                strength[y] += [1 - s for s in t.scores]
            for f in ("fights", "draws", "reached_round_2", "round0_ko", "trailing_after_r0", "trailing_won",
                      "exhausted_beats", "executed_beats", "kos", "decisions", "opening_bonus_hp", "power_bonus_hp",
                      "leader_after_r1", "leader_after_r1_won"):
                setattr(total, f, getattr(total, f) + getattr(t, f))
            for act, row in t.action_beats.items():
                acc = total.action_beats.setdefault(act, [0, 0, 0])
                for k in range(3):
                    acc[k] += row[k]
    shape = {
        "draws": total.draws / total.fights,
        "round2": total.reached_round_2 / total.fights,
        "round0_ko": total.round0_ko / total.fights,
        "trailer_wins": total.trailing_won / max(1, total.trailing_after_r0),
        "exhausted": total.exhausted_beats / max(1, total.executed_beats),
        "strength": {n: E.mean(s) for n, s in strength.items()},
        # Reported, not gated: the AUD-021 balance measures.
        "ko_rate": total.kos / total.fights,
        "decision_rate": total.decisions / total.fights,
        "beats_per_fight": total.executed_beats / total.fights,
        "opening_bonus_per_side": total.opening_bonus_hp / total.fights,
        "power_bonus_per_side": total.power_bonus_hp / total.fights,
        "leader_after_r1_wins": total.leader_after_r1_won / max(1, total.leader_after_r1),
        "actions": {act: {"share": row[0] / max(1, total.executed_beats), "net_per_beat": (row[1] - row[2]) / row[0]}
                    for act, row in sorted(total.action_beats.items()) if row[0]},
    }
    families = [n for n, s in shape["strength"].items() if s >= 0.45]
    raw["shape"], raw["shape_matrix"] = shape, matrix
    gates += [
        gate("Draws <=15%", shape["draws"] <= 0.15, f"{shape['draws']:.1%}"),
        gate("Fights reaching round 2 >=40%", shape["round2"] >= 0.40, f"{shape['round2']:.1%}"),
        gate("Round-0 knockouts <=20%", shape["round0_ko"] <= 0.20, f"{shape['round0_ko']:.1%}"),
        gate("Trailing-after-round-0 wins in 10..40%", 0.10 <= shape["trailer_wins"] <= 0.40,
             f"{shape['trailer_wins']:.1%}"),
        gate("Exhausted beats <10% for competent policies", shape["exhausted"] < 0.10, f"{shape['exhausted']:.1%}"),
        gate(">=3 strategy families score >=0.45 against the pool", len(families) >= 3,
             ", ".join(f"{n} {s:.3f}" for n, s in shape["strength"].items())),
    ]
    sections.append(E.markdown("Competent-pool round robin", matrix))
    sections.append(
        "### Fight shape and action value (competent pool, reported, not gated)\n\n"
        f"KO {shape['ko_rate']:.1%}, decision {shape['decision_rate']:.1%}, draws {shape['draws']:.1%}; "
        f"{shape['beats_per_fight']:.1f} executed beats per fight; the HP leader after round 1 (of 0..2) wins "
        f"{shape['leader_after_r1_wins']:.1%}; opening bonus {shape['opening_bonus_per_side']:.1f} and power bonus "
        f"{shape['power_bonus_per_side']:.1f} HP per fighter and fight. Each fight counts once per side "
        "(net = damage dealt minus damage taken on beats where that side executed the action).\n\n"
        "| Action | Share of executed beats | Net HP per beat |\n|---|---:|---:|\n"
        + "\n".join(f"| {k} | {v['share']:.1%} | {v['net_per_beat']:+.2f} |" for k, v in shape["actions"].items()) + "\n")

    elapsed = time.time() - started
    passed = sum(g["pass"] for g in gates)
    lines = [
        f"# Combat {rules.semantic_version.removeprefix('combat-v1-').replace('-', ' ')} — strategic validation report", "",
        f"Generated by `scripts/combat-validation.py` with the instruments of commit {commit}, "
        f"ruleset `{rules.digest.hex()}` ({rules.semantic_version}).",
        f"Hardware: {platform.machine()}, Python {platform.python_version()}, 2 CPUs; runtime {elapsed / 60:.1f} min.",
        f"Budgets: {a.seeds} paired seeds for cheap policies; {a.costly_seeds} (x4 where a gate needs 2000 fights) for "
        f"search-v1 ({a.search_candidates} candidate plans x {a.search_samples} samples) and reader-v1 "
        "(beam 32 over 2 repeat + 2 hedge predictions).",
        "Uncertainty: paired bootstrap (2000 resamples), 2.5th percentile of the per-seed mean.",
        "Instruments were developed on `train/...` seed suites; every number below uses the "
        f"`{a.suite}/...` suites, first used by this run.", "",
        f"**{passed}/{len(gates)} gates pass.** This report records measurements; it does not waive a failed gate.",
        "Not measured here: adaptation time against a style-switching opponent, economics, latency and "
        "contract cost (model.md §4-6).", "",
        "| Gate | Result | Measured |", "|---|---|---|",
        *[f"| {g['gate']} | {'PASS' if g['pass'] else '**FAIL**'} | {g['detail']} |" for g in gates], "",
        *sections,
    ]
    Path(a.out).write_text("\n".join(lines) + "\n")
    Path(a.out).with_suffix(".json").write_text(json.dumps({"gates": gates, **raw}, indent=1, default=str) + "\n")
    log(f"wrote {a.out}: {passed}/{len(gates)} gates pass")


if __name__ == "__main__":
    main()
