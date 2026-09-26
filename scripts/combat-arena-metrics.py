#!/usr/bin/env python3
"""Arena health, fairness and economics, measured on a simulated demo arena.

Runs the live demo arena (`combat/live.py`) in a temporary directory with
tick_seconds=0 for a lineup like the public one. LLM planners are replaced by
an in-process policy (default mixed-v1, about their measured strength). It then
reports what the 2026-09-25 simulation audit measured on the live arena:

- house P&L per fight: the house's rake share minus simulated execution fees
  and cup sponsorship paid out;
- expected value per fighter, grouped by ranked strength;
- cup and duel win concentration;
- rating spread over time (convergence) and how often the top pair meets;
- season champions and whether the best fighters qualified;
- market prices, when the arena runs a priced market.

  uv run python scripts/combat-arena-metrics.py --ticks 10000 --seed 1 --json out.json

Contests are collected while the arena runs, so the numbers do not depend on
how much finished history the arena keeps in memory.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import codec, live  # noqa: E402
from qdojo.combat.codec import Mode  # noqa: E402

DEFAULT_LINEUP = Path.home() / ".qdojo/combat/lineup-arena.json"


def stub_llms(lineup: list[dict], policy: str) -> list[dict]:
    """LLM entries become an in-process policy; everything else is kept."""
    out = []
    for e in lineup:
        if "llm" in e or "planner" in e:
            e = {k: v for k, v in e.items() if k not in ("llm", "planner", "budget_ms")}
            e["policy"] = policy
            e["stubbed"] = True
        out.append(e)
    return out


class Collector:
    """Finished contests and cups, gathered while the arena runs."""

    def __init__(self, arena):
        self.a = arena
        self.contests: dict[int, dict] = {}
        self.cups: dict[int, dict] = {}
        self.ratings: list[tuple[int, dict]] = []
        self.rounds = 0

    def sweep(self):
        c = self.a.w.contract
        for ct in list(c.contests.values()):
            if ct.status != "DONE" or ct.contest_id in self.contests:
                continue
            r = ct.result or {}
            sides = {}
            for s, p in (("A", ct.a), ("B", ct.b)):
                credit = (ct.settlement or {}).get("credits", {}).get(p.payout_recipient, 0)
                sides[s] = {"fid": p.fighter_id, "rating": p.lifetime_rating, "returned": credit}
            self.contests[ct.contest_id] = {
                "mode": Mode(ct.mode).name.lower(), "stake": ct.stake, "kind": r.get("kind"),
                "winner": r.get("winner"), "fights": len(ct.fights), "sides": sides, "tick": r.get("tick"),
                "fight_rounds": sum(len(c.fights[f].rounds) for f in ct.fights if f in c.fights),
                "fight_kinds": [(c.fights[f].result or {}).get("kind") for f in ct.fights if f in c.fights],
                "fight_winners": [(c.fights[f].result or {}).get("winner") for f in ct.fights if f in c.fights]}
        for k in c.cups.values():
            if k.status in ("COMPLETE", "CANCELLED", "ABORTED") and k.cup_id not in self.cups:
                self.cups[k.cup_id] = {"status": k.status, "champion": k.champion, "sponsorship": k.sponsorship,
                                       "entries": {f: e.amount for f, e in k.entries.items()},
                                       "fee_profile_id": k.descriptor["fee_profile_id"]}

    def sample_ratings(self):
        c = self.a.w.contract
        self.ratings.append((self.a.w.tick, {f: x.lifetime for f, x in c.fighters.items() if x.placement >= 10}))


def spread(r: dict) -> dict:
    v = sorted(r.values())
    if len(v) < 2:
        return {"n": len(v), "range": 0, "stdev": 0.0, "iqr": 0}
    q = statistics.quantiles(v, n=4)
    return {"n": len(v), "range": v[-1] - v[0], "stdev": round(statistics.pstdev(v), 1), "iqr": round(q[2] - q[0])}


def analyse(arena, col: Collector, ticks: int, runtime: float) -> dict:
    c = arena.w.contract
    m = arena.net.m
    fee = m.fees[1]
    names = {fid: e["label"] for fid, e in arena.labels.items()}
    policy = {fid: ("stub:" if e.get("stubbed") else "") + (e.get("policy") or "?") for fid, e in arena.labels.items()}
    done = [x for x in col.contests.values() if x["kind"] != "VOID"]
    fights = sum(x["fights"] for x in done)
    by_mode = collections.Counter()
    for x in done:
        by_mode[x["mode"]] += x["fights"]

    # ---- money --------------------------------------------------------------
    credits = c.ledger.credits
    house, dev, share = credits.get(fee.house, 0), credits.get(fee.dev, 0), credits.get(fee.share, 0)
    sponsorship = sum(k["sponsorship"] for k in col.cups.values() if k["status"] == "COMPLETE")
    burned = arena.chain.burned
    market = getattr(arena, "market", None)
    market_fees = market.fees_collected() if market is not None else 0
    house_pnl = house + market_fees - burned - sponsorship
    calls = collections.Counter()
    for tx in arena.chain.txs.values():
        if tx.status == "included":
            op = int.from_bytes(tx.frame[len(codec.FRAME_MAGIC):len(codec.FRAME_MAGIC) + 2], "little")
            calls[codec.Op(op).name if op in codec.Op._value2member_map_ else "?"] += 1

    # ---- per fighter ----------------------------------------------------------
    per = {fid: {"name": names.get(fid, fid.hex()[:8]), "policy": policy.get(fid, "?"),
                 "ranked_fights": 0, "ranked_points": 0.0, "ranked_net": 0,
                 "duel_series": 0, "duel_series_won": 0, "duel_net": 0, "cup_net": 0, "cups_won": 0}
           for fid in c.fighters}
    pairs = collections.Counter()
    for x in done:
        a, b = x["sides"]["A"], x["sides"]["B"]
        if x["mode"] == "ranked":
            pairs[tuple(sorted((a["fid"], b["fid"])))] += 1
        if x["mode"] in ("ranked", "duel"):
            for s, side in (("A", a), ("B", b)):
                row = per[side["fid"]]
                net = side["returned"] - x["stake"]
                if x["mode"] == "ranked":
                    row["ranked_fights"] += 1
                    row["ranked_net"] += net
                    row["ranked_points"] += 1.0 if x["winner"] == s else 0.5 if x["winner"] is None else 0.0
                else:
                    row["duel_series"] += 1
                    row["duel_series_won"] += x["winner"] == s
                    row["duel_net"] += net
    for k in col.cups.values():
        if k["status"] != "COMPLETE":
            continue
        gross = sum(k["entries"].values())
        rake = gross * m.fees[k["fee_profile_id"]].rake_bps // 10_000
        for fid, amount in k["entries"].items():
            per[fid]["cup_net"] -= amount
        per[k["champion"]]["cup_net"] += k["sponsorship"] + gross - rake
        per[k["champion"]]["cups_won"] += 1
    for fid, row in per.items():
        row["rating"] = c.fighters[fid].lifetime
        row["ranked_score"] = round(row["ranked_points"] / row["ranked_fights"], 3) if row["ranked_fights"] else None
        row["ranked_net_per_fight"] = round(row["ranked_net"] / row["ranked_fights"], 1) if row["ranked_fights"] else None
        row["total"] = row["ranked_net"] + row["duel_net"] + row["cup_net"]
        del row["ranked_points"]

    def bucket(row):
        s = row["ranked_score"]
        if s is None or row["ranked_fights"] < 20:
            return None
        return "strong (>0.55)" if s > 0.55 else "average (0.45-0.55)" if s >= 0.45 else "weak (<0.45)"
    buckets = collections.defaultdict(lambda: {"fighters": 0, "fights": 0, "net": 0})
    for row in per.values():
        b = bucket(row)
        if b:
            buckets[b]["fighters"] += 1
            buckets[b]["fights"] += row["ranked_fights"]
            buckets[b]["net"] += row["ranked_net"]
    ev = {b: {**v, "net_per_fight": round(v["net"] / v["fights"], 1)} for b, v in sorted(buckets.items())}

    # ---- concentration --------------------------------------------------------
    champs = collections.Counter(k["champion"] for k in col.cups.values() if k["status"] == "COMPLETE")
    cups_complete = sum(champs.values())
    duel_wins = collections.Counter()
    duel_total = 0
    for x in done:
        if x["mode"] == "duel":
            duel_total += 1
            if x["winner"]:
                duel_wins[x["sides"][x["winner"]]["fid"]] += 1
    top_champ = champs.most_common(1)
    top_duel = duel_wins.most_common(1)

    # ---- ratings and matchmaking ---------------------------------------------
    samples = [(t, spread(r)) for t, r in col.ratings]
    ranked_total = sum(pairs.values())
    rated = sorted((f for f in c.fighters if c.fighters[f].placement >= 10), key=lambda f: -c.fighters[f].lifetime)
    top_pair = None
    if len(rated) >= 2:
        p = tuple(sorted(rated[:2]))
        both = per[rated[0]]["ranked_fights"] + per[rated[1]]["ranked_fights"] - pairs[p]
        top_pair = {"pair": [names[rated[0]], names[rated[1]]], "meetings": pairs[p],
                    "share_of_their_fights": round(pairs[p] / both, 3) if both else None}
    common = pairs.most_common(1)
    drift = None
    if len(col.ratings) >= 3:
        t0, r0 = col.ratings[-len(col.ratings) // 3]
        t1, r1 = col.ratings[-1]
        common_f = set(r0) & set(r1)
        if common_f and t1 > t0:
            drift = round(sum(abs(r1[f] - r0[f]) for f in common_f) / len(common_f) * 1000 / (t1 - t0), 1)

    # ---- seasons ----------------------------------------------------------------
    seasons = []
    std = getattr(arena, "season_standings", None) or (lambda s, t: c.season_standings(s, t))
    for s in sorted({s for f in c.fighters.values() for s in f.season_stats}):
        st = std(s, c.tick)
        if not st["final"]:
            continue
        champ = st["champion"]
        seasons.append({"season": s, "status": st["status"], "champion": names.get(champ) if champ else None,
                        "champion_lifetime_rank": (rated.index(champ) + 1) if champ in rated else None,
                        "top3_qualified": [bool(next((r["qualified"] for r in st["standings"]
                                                      if r["fighter_id"] == f), False)) for f in rated[:3]],
                        "qualified": sum(1 for r in st["standings"] if r["qualified"])})

    # House net per fight by mode: its rake share from that mode's pots, less
    # the average execution cost per fight, less sponsorship for cups.
    exec_fight = burned / fights if fights else 0
    by_mode_house = collections.Counter()
    for x in done:
        if x["mode"] in ("ranked", "duel") and x["winner"] is not None and x["kind"] in ("COMBAT", "FORFEIT"):
            by_mode_house[x["mode"]] += 2 * x["stake"] * fee.rake_bps // 10_000 * fee.house_bps // 10_000
    for k in col.cups.values():
        if k["status"] == "COMPLETE":
            f2 = m.fees[k["fee_profile_id"]]
            by_mode_house["cup"] += sum(k["entries"].values()) * f2.rake_bps // 10_000 * f2.house_bps // 10_000
            by_mode_house["cup"] -= k["sponsorship"]
    house_by_mode = {mode: round(by_mode_house[mode] / n - exec_fight, 1) for mode, n in by_mode.items() if n}

    out = {
        "ticks": ticks, "runtime_s": round(runtime, 1), "profile": arena.net.profile,
        "tier_stake": getattr(arena, "tier_stake", m.tiers[min(m.tiers)]),
        "ranked_house_net": house_by_mode.get("ranked"), "house_net_by_mode": house_by_mode,
        "fights": fights, "fights_by_mode": dict(by_mode), "contests": len(done),
        "money": {"house_rake": house, "dev": dev, "share": share, "execution_fees": burned,
                  "sponsorship_paid": sponsorship, "market_fees": market_fees, "house_pnl": house_pnl,
                  "house_pnl_per_fight": round(house_pnl / fights, 1) if fights else None,
                  "exec_per_fight": round(burned / fights, 1) if fights else None,
                  "house_rake_per_fight": round(house / fights, 1) if fights else None,
                  "calls": dict(calls), "calls_per_fight": round(sum(calls.values()) / fights, 1) if fights else None},
        "ev_by_strength": ev,
        "fighters": sorted(per.values(), key=lambda r: -r["rating"]),
        "cups": {"complete": cups_complete, "cancelled_or_aborted": len(col.cups) - cups_complete,
                 "top": [names[top_champ[0][0]], top_champ[0][1]] if top_champ else None,
                 "top_share": round(top_champ[0][1] / cups_complete, 3) if top_champ else None,
                 "champions": {names[f]: n for f, n in champs.most_common()}},
        "duels": {"series": duel_total, "top": [names[top_duel[0][0]], top_duel[0][1]] if top_duel else None,
                  "top_share": round(top_duel[0][1] / duel_total, 3) if top_duel else None,
                  "wins": {names[f]: n for f, n in duel_wins.most_common()}},
        "ratings": {"samples": [{"tick": t, **s} for t, s in samples[::max(1, len(samples) // 8)]] + (
                        [{"tick": samples[-1][0], **samples[-1][1]}] if samples else []),
                    "final": samples[-1][1] if samples else None,
                    "mean_abs_drift_per_1000_ticks_last_third": drift},
        "matchmaking": {"ranked_fights": ranked_total, "top_pair": top_pair,
                        "most_common_pair": ([names[common[0][0][0]], names[common[0][0][1]], common[0][1]]
                                             if common else None),
                        "most_common_pair_share": round(common[0][1] / ranked_total, 3) if common else None},
        "seasons": seasons,
    }
    if market is not None:
        out["market"] = market.summary()
    return out


def run(lineup, ticks, seed, profile="demo", sample_every=250, export_every=0, **kw):
    with tempfile.TemporaryDirectory(prefix="qdojo-metrics-") as tmp:
        arena = live.Arena(Path(tmp) / "arena", lineup, profile=profile, seed=seed, deterministic=True,
                           log=lambda m: None, **kw)
        col = Collector(arena)
        started = time.time()
        for i in range(1, ticks + 1):
            arena.step()
            if i % 100 == 0:
                col.sweep()
            if i % sample_every == 0:
                col.sample_ratings()
            if export_every and i % export_every == 0:
                from qdojo.combat import export
                export.export_all(arena.w.contract, Path(tmp) / "combat/v1", keep=200,
                                  deployment=arena.deployment(0))
            if hasattr(arena, "maintain"):
                arena.maintain()
        col.sweep()
        col.sample_ratings()
        result = analyse(arena, col, ticks, time.time() - started)
        from qdojo.combat import export
        root = Path(tmp) / "combat/v1"
        export.export_all(arena.w.contract, root, keep=200, deployment=arena.deployment(0))
        result["index_json_bytes"] = (root / "index.json").stat().st_size
    return result


def table(res: dict) -> str:
    m = res["money"]
    lines = [f"## {res.get('label', 'run')}: {res['ticks']} ticks, {res['fights']} fights {res['fights_by_mode']}", "",
             f"- house P&L {m['house_pnl']:+,} QU = rake {m['house_rake']:,} + market {m['market_fees']:,} "
             f"- execution {m['execution_fees']:,} - sponsorship {m['sponsorship_paid']:,}; "
             f"per fight {m['house_pnl_per_fight']:+} (rake {m['house_rake_per_fight']}, exec {m['exec_per_fight']}, "
             f"{m['calls_per_fight']} calls); by mode {res.get('house_net_by_mode')}",
             f"- EV by strength: " + "; ".join(f"{b}: {v['net_per_fight']:+} QU/fight ({v['fighters']} fighters)"
                                                for b, v in res["ev_by_strength"].items()),
             f"- cups: {res['cups']['complete']} complete, top {res['cups']['top']} share {res['cups']['top_share']}",
             f"- duels: {res['duels']['series']} series, top {res['duels']['top']} share {res['duels']['top_share']}",
             f"- ratings final {res['ratings']['final']}, drift {res['ratings']['mean_abs_drift_per_1000_ticks_last_third']}",
             f"- top pair {res['matchmaking']['top_pair']}; most common pair {res['matchmaking']['most_common_pair']}",
             f"- seasons {res['seasons']}",
             f"- index.json {res['index_json_bytes']:,} bytes; runtime {res['runtime_s']} s", "",
             "| Fighter | Policy | Rating | Ranked n | Score | Net/fight | Duel W/n | Duel net | Cups | Cup net | Total |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res["fighters"]:
        lines.append(f"| {r['name']} | {r['policy']} | {r['rating']} | {r['ranked_fights']} | {r['ranked_score']} | "
                     f"{r['ranked_net_per_fight']} | {r['duel_series_won']}/{r['duel_series']} | {r['duel_net']:+} | "
                     f"{r['cups_won']} | {r['cup_net']:+} | {r['total']:+} |")
    if "market" in res:
        lines += ["", f"- market: {res['market']}"]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticks", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--lineup", default=str(DEFAULT_LINEUP))
    p.add_argument("--llm-policy", default="mixed-v1", help="policy standing in for LLM planners")
    p.add_argument("--profile", default="demo")
    p.add_argument("--label", default="run")
    p.add_argument("--json", help="write the full result here")
    a = p.parse_args()
    path = Path(a.lineup)
    lineup = json.loads(path.read_text()) if path.exists() else live.DEFAULT_LINEUP
    res = run(stub_llms(lineup, a.llm_policy), a.ticks, a.seed, a.profile)
    res["label"] = a.label
    print(table(res))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
