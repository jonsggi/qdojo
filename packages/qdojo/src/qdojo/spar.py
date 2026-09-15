"""The sparring dojo: rounds back to back with generated riddles, and a
metrics row per round so money flow, solve rates and fighter behaviour can
be read afterwards."""
import json
import os
import random
import sys
import time

from . import riddles
from .house import HouseError
from .chain.base import Unknown


def log(msg):
    print(time.strftime("%H:%M:%SZ", time.gmtime()), msg, flush=True)


class Spar:
    def __init__(self, house, belts, entry_fee, commit_window, reveal_window, riddle_dir, web_out, metrics_path,
                 seed=None, payout_mode=1, poll=15):
        self.h, self.belts = house, belts
        self.entry_fee, self.wc, self.wr = entry_fee, commit_window, reveal_window
        self.riddle_dir, self.web_out, self.metrics_path = riddle_dir, web_out, metrics_path
        self.rng = random.Random(seed)
        self.payout_mode, self.poll = payout_mode, poll
        os.makedirs(riddle_dir, mode=0o700, exist_ok=True)

    def _export(self):
        try:
            self.h.collect()
        except (Unknown, HouseError) as e:
            log(f"collect: {e}")
        try:
            self.h.export(self.web_out)
        except (Unknown, HouseError) as e:
            log(f"export: {e}")

    def one_round(self, belt: str) -> dict | None:
        rid = self.h.state()["next_round"]
        r = riddles.generate(belt, self.rng, rid)
        path = os.path.join(self.riddle_dir, f"{rid:04d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)
        os.chmod(path, 0o600)
        before = self.h.chain.balance(self.h.identity)
        meta = self.h.publish(path, self.entry_fee, self.wc, self.wr, payout_mode=self.payout_mode)
        log(f"round {rid} [{belt}/{r['kind']}] PUBLISH {meta['publish_tx'][:8]}… sched {meta['scheduled_tick']}")
        for _ in range(120):
            try:
                meta = self.h.confirm_publish(rid)
                break
            except Unknown:
                time.sleep(2)
        if meta["status"] != "open":
            log(f"round {rid} publish {meta['status']}; skipping")
            return None
        spec = self.h.spec(rid)
        log(f"round {rid} open at {spec.publish_tick}, commit until {spec.commit_end}, reveal until {spec.reveal_end}")
        self._export()
        while self.h.state()["scanned_to"] <= spec.reveal_end:
            time.sleep(self.poll)
            self._export()
        doc = None
        for attempt in range(40):
            try:
                doc = self.h.settle(rid, apply=True)
                if self.h.meta(rid)["status"] == "settled":
                    break
            except (HouseError, Unknown) as e:
                log(f"settle attempt {attempt + 1}: {e}")
            time.sleep(self.poll)
        self._export()
        after = self.h.chain.balance(self.h.identity)
        row = self.metrics_row(rid, belt, r, spec, doc, before, after)
        with open(self.metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        log(f"round {rid} settled: pot {row['pot']} winners {[e['name'] or e['identity'][:6] for e in row['entries'] if e['verdict']=='winner']} "
            f"solved {row['n_solved']}/{row['n_entries']} house {before}->{after}")
        return row

    def metrics_row(self, rid, belt, r, spec, doc, before, after) -> dict:
        names = {k: v["name"] for k, v in self.h.bows().items()}
        entries = []
        for e in (doc or {}).get("entries", []):
            entries.append({"identity": e["identity"], "name": names.get(e["identity"]), "verdict": e["verdict"],
                            "stake": e["stake"], "commit_latency_ticks": e["commit_tick"] - spec.publish_tick,
                            "reveal_latency_ticks": (e["reveal_tick"] - spec.reveal_start) if e["reveal_tick"] else None,
                            "answer": e["answer"]})
        solved = [e for e in entries if e["verdict"] in ("winner", "solved")]
        payouts = (doc or {}).get("payouts", [])
        return {"round_id": rid, "belt": belt, "kind": r["kind"], "title": r["title"], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "publish_tick": spec.publish_tick, "entry_fee": spec.entry_fee, "house_seed": spec.house_seed,
                "payout_mode": spec.payout_mode, "settled": bool(doc) and self.h.meta(rid)["status"] == "settled",
                "pot": (doc or {}).get("pot"), "rake": (doc or {}).get("rake"), "carry": (doc or {}).get("carry"),
                "n_entries": len(entries), "n_solved": len(solved),
                "first_solve_latency_ticks": min((e["commit_latency_ticks"] for e in solved), default=None),
                "stakes_in": sum(e["stake"] for e in entries),
                "payouts_out": sum(p["amount"] for p in payouts if p["confirmed"]),
                "house_before": before, "house_after": after, "house_delta": after - before,
                "entries": entries, "payouts": [{"identity": p["identity"], "amount": p["amount"], "kind": p["kind"]} for p in payouts],
                "strikes": (doc or {}).get("strikes", {})}

    def run(self, rounds: int, stop_below: int = 0):
        for i in range(rounds):
            belt = self.belts[i % len(self.belts)]
            bal = self.h.chain.balance(self.h.identity)
            if bal < max(stop_below, self.h.seed_per_round + self.h.state()["carry"]):
                log(f"house balance {bal} too low to seed the next round; stopping")
                return
            try:
                self.one_round(belt)
            except (HouseError, Unknown) as e:
                log(f"round aborted: {e}")
                time.sleep(self.poll)


def summarize(metrics_path: str) -> dict:
    rows = [json.loads(l) for l in open(metrics_path, encoding="utf-8") if l.strip()]
    by_belt, fighters = {}, {}
    for r in rows:
        b = by_belt.setdefault(r["belt"], {"rounds": 0, "solved_rounds": 0, "latencies": []})
        b["rounds"] += 1
        if r["n_solved"]:
            b["solved_rounds"] += 1
            b["latencies"].append(r["first_solve_latency_ticks"])
        for e in r["entries"]:
            f = fighters.setdefault(e["name"] or e["identity"][:8], {"rounds": 0, "solved": 0, "wins": 0, "stakes": 0, "earned": 0, "latencies": []})
            f["rounds"] += 1; f["stakes"] += e["stake"]
            if e["verdict"] in ("winner", "solved"):
                f["solved"] += 1; f["latencies"].append(e["commit_latency_ticks"])
            if e["verdict"] == "winner":
                f["wins"] += 1
        for p in r["payouts"]:
            name = next((e["name"] or e["identity"][:8] for e in r["entries"] if e["identity"] == p["identity"]), p["identity"][:8])
            fighters.setdefault(name, {"rounds": 0, "solved": 0, "wins": 0, "stakes": 0, "earned": 0, "latencies": []})
            if p["kind"] == "win":
                fighters[name]["earned"] += p["amount"]
    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None
    return {"rounds": len(rows), "settled": sum(1 for r in rows if r["settled"]),
            "money": {"stakes_in": sum(r["stakes_in"] for r in rows), "payouts_out": sum(r["payouts_out"] for r in rows),
                      "house_delta": sum(r["house_delta"] for r in rows), "carry_now": rows[-1]["carry"] if rows else 0},
            "belts": {k: {"rounds": v["rounds"], "solve_rate": round(v["solved_rounds"] / v["rounds"], 2),
                          "avg_first_solve_ticks": avg(v["latencies"])} for k, v in by_belt.items()},
            "fighters": {k: {"rounds": v["rounds"], "solved": v["solved"], "wins": v["wins"], "stakes": v["stakes"],
                             "earned": v["earned"], "net": v["earned"] - v["stakes"], "avg_solve_ticks": avg(v["latencies"])}
                         for k, v in sorted(fighters.items(), key=lambda kv: -(kv[1]["earned"] - kv[1]["stakes"]))}}
