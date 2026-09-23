#!/usr/bin/env python3
"""Run the docs/model.md §2 strategic campaign for a ruleset and write a report.

Every gate is evaluated and printed PASS or FAIL with its numbers; failures
are reported, never dropped. Test seeds (suite "test/...") are disjoint from
anything a policy could have been tuned on, and the fixed-style pool includes
withheld parameter variants.

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
from qdojo.combat.rules import candidate_1  # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def gate(name, ok, detail):
    return {"gate": name, "pass": bool(ok), "detail": detail}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seeds", type=int, default=1000, help="paired seeds per matchup (fights = 2x)")
    p.add_argument("--search-seeds", type=int, default=250, help="paired seeds for the costly search planner")
    p.add_argument("--search-candidates", type=int, default=60)
    p.add_argument("--search-samples", type=int, default=8)
    p.add_argument("--out", default=str(ROOT / "docs/validation-report.md"))
    a = p.parse_args()
    rules = candidate_1()
    pools = E.pools()
    search = E.SearchPlanner(candidates=a.search_candidates, samples=a.search_samples)
    blind = E.SearchPlanner(candidates=a.search_candidates, samples=a.search_samples, use_history=False)
    nores = E.SearchPlanner(candidates=a.search_candidates, samples=a.search_samples, ignore_resources=True)
    started = time.time()
    gates, sections, raw = [], [], {}

    # 1. Baselines and obvious exploits: every simple strategy needs a practical counter.
    simple = {k: v for k, v in pools["baseline"].items() if k not in ("mixed-v1", "scout-v1", "random-v1")}
    counters = {"scout-v1": npcs.ROSTER["scout-v1"].policy, "mixed-v1": npcs.ROSTER["mixed-v1"].policy}
    rows, missing = [], []
    for name, pol in simple.items():
        log(f"counter search for {name}")
        opening, _ = E.best_response_opening(rules, pol, samples=1 if name not in ("repeat-last-winner",) else 4)
        cands = dict(counters, **{"br-opening+scout": E.exploit_opening(opening, npcs.scout_v1)})
        best = None
        for cname, cpol in cands.items():
            r = E.summarize(name, E.paired(cpol, pol, a.seeds, f"test/counter/{name}"))
            r["counter"] = cname
            if best is None or r["lower95"] > best["lower95"]:
                best = r
        rows.append(best)
        if not (best["score"] >= 0.60 and best["lower95"] > 0.55):
            missing.append(name)
    raw["counters"] = rows
    gates.append(gate("Every simple strategy has a counter (>=0.60, LB>0.55)", not missing,
                      f"{len(rows) - len(missing)}/{len(rows)} countered" + (f"; uncountered: {', '.join(missing)}" if missing else "")))
    sections.append("### Best counter per simple strategy\n\n| Strategy | Counter | Score | 95% LB | Fights |\n|---|---|---:|---:|---:|\n"
                    + "\n".join(f"| {r['opponent']} | {r['counter']} | {r['score']:.3f} | {r['lower95']:.3f} | {r['fights']} |" for r in rows) + "\n")

    # 2. Optimization reward.
    log("optimization reward")
    planners = {"scout-v1": npcs.ROSTER["scout-v1"].policy, "search-v1": search}
    reward = {}
    for pname, pol in planners.items():
        seeds = a.search_seeds if pname == "search-v1" else a.seeds
        vs_random = E.summarize("random-v1", E.paired(pol, npcs.random_v1, seeds, "test/reward/random"))
        style_scores = []
        for oname, opol in pools["fixed-style"].items():
            t = E.paired(pol, opol, max(1, seeds // len(pools["fixed-style"]) * 2), f"test/reward/{oname}")
            style_scores += t.scores
        style = {"score": E.mean(style_scores), "lower95": E.bootstrap_lower(style_scores), "fights": 2 * len(style_scores)}
        reward[pname] = {"random": vs_random, "fixed_style": style}
    raw["reward"] = reward
    ok = any(r["random"]["score"] >= 0.65 and r["random"]["lower95"] > 0.60 and r["random"]["fights"] >= 2000
             and r["fixed_style"]["score"] >= 0.60 and r["fixed_style"]["lower95"] > 0.55 and r["fixed_style"]["fights"] >= 2000
             for r in reward.values())
    gates.append(gate("A <=1500 ms planner beats random (>=0.65, LB>0.60) and fixed styles (>=0.60, LB>0.55), >=2000 fights each", ok,
                      "; ".join(f"{k}: random {v['random']['score']:.3f} (LB {v['random']['lower95']:.3f}, {v['random']['fights']}), "
                                f"styles {v['fixed_style']['score']:.3f} (LB {v['fixed_style']['lower95']:.3f}, {v['fixed_style']['fights']})"
                                for k, v in reward.items())))

    # 3. Ablations on the same held-out pool.
    log("ablations")
    held = pools["fixed-style"]
    res_ab = E.ablation(search, nores, held, max(1, a.search_seeds // len(held)), "test/ablation/resources")
    hist_ab = E.ablation(search, blind, held, max(1, a.search_seeds // len(held)), "test/ablation/history")
    raw["ablation"] = {"resources": res_ab, "history": hist_ab}
    gates.append(gate("Resource/opening state matters (improvement >=0.05, LB>0)",
                      res_ab["mean_improvement"] >= 0.05 and res_ab["lower95"] > 0,
                      f"+{res_ab['mean_improvement']:.3f} (LB {res_ab['lower95']:.3f}, {res_ab['pairs']} pairs)"))
    gates.append(gate("History-aware beats history-blind on predictable families (>=0.05, LB>0)",
                      hist_ab["mean_improvement"] >= 0.05 and hist_ab["lower95"] > 0,
                      f"+{hist_ab['mean_improvement']:.3f} (LB {hist_ab['lower95']:.3f}, {hist_ab['pairs']} pairs)"))

    # 4. Fight shape on the competent pool (round robin, excluding passive NPCs).
    log("fight shape")
    competent = {"mixed-v1": npcs.mixed_v1, "scout-v1": npcs.scout_v1, "repeat-last-winner": E.repeat_last_winner,
                 "search-v1": search}
    names = list(competent)
    total = E.Tally()
    strength = {n: [] for n in names}
    matrix = []
    for i, x in enumerate(names):
        for y in names[i:]:
            seeds = a.search_seeds if "search-v1" in (x, y) else a.seeds
            t = E.paired(competent[x], competent[y], seeds, f"test/shape/{x}/{y}")
            row = E.summarize(f"{x} vs {y}", t)
            matrix.append(row)
            strength[x] += t.scores
            if x != y:
                strength[y] += [1 - s for s in t.scores]
            for f in ("fights", "draws", "reached_round_2", "round0_ko", "trailing_after_r0", "trailing_won",
                      "exhausted_beats", "executed_beats"):
                setattr(total, f, getattr(total, f) + getattr(t, f))
    shape = {
        "draws": total.draws / total.fights,
        "round2": total.reached_round_2 / total.fights,
        "round0_ko": total.round0_ko / total.fights,
        "trailer_wins": total.trailing_won / max(1, total.trailing_after_r0),
        "exhausted": total.exhausted_beats / max(1, total.executed_beats),
        "families_ge_045": [n for n, s in strength.items() if E.mean(s) >= 0.45],
    }
    raw["shape"] = shape
    raw["shape_matrix"] = matrix
    gates += [
        gate("Draws <=15%", shape["draws"] <= 0.15, f"{shape['draws']:.1%}"),
        gate("Fights reaching round 2 >=40%", shape["round2"] >= 0.40, f"{shape['round2']:.1%}"),
        gate("Round-0 knockouts <=20%", shape["round0_ko"] <= 0.20, f"{shape['round0_ko']:.1%}"),
        gate("Trailing-after-round-0 wins in 10..40%", 0.10 <= shape["trailer_wins"] <= 0.40, f"{shape['trailer_wins']:.1%}"),
        gate("Exhausted beats <10% for competent policies", shape["exhausted"] < 0.10, f"{shape['exhausted']:.1%}"),
        gate(">=3 strategy families score >=0.45 against the pool", len(shape["families_ge_045"]) >= 3,
             ", ".join(f"{n} {E.mean(strength[n]):.3f}" for n in names)),
    ]
    sections.append(E.markdown("Competent-pool round robin", matrix))

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    elapsed = time.time() - started
    passed = sum(g["pass"] for g in gates)
    lines = [
        "# Combat candidate 1 — strategic validation report", "",
        f"Generated by `scripts/combat-validation.py` at commit {commit}, "
        f"ruleset `{rules.digest.hex()}` ({rules.semantic_version}).",
        f"Hardware: {platform.machine()}, {platform.processor() or 'unknown CPU'}, Python {platform.python_version()}; "
        f"runtime {elapsed / 60:.1f} min.",
        f"Budgets: {a.seeds} paired seeds for cheap policies, {a.search_seeds} for search-v1 "
        f"({a.search_candidates} candidate plans x {a.search_samples} opponent samples per round).",
        "Uncertainty: paired bootstrap (2000 resamples) 2.5th percentile of the per-seed mean.", "",
        f"**{passed}/{len(gates)} gates pass.** This report records measurements; it does not waive a failed gate.", "",
        "| Gate | Result | Measured |", "|---|---|---|",
        *[f"| {g['gate']} | {'PASS' if g['pass'] else '**FAIL**'} | {g['detail']} |" for g in gates], "",
        *sections,
    ]
    Path(a.out).write_text("\n".join(lines) + "\n")
    Path(a.out).with_suffix(".json").write_text(json.dumps({"gates": gates, **raw}, indent=1, default=str) + "\n")
    log(f"wrote {a.out}: {passed}/{len(gates)} gates pass")


if __name__ == "__main__":
    main()
