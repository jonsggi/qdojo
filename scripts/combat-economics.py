#!/usr/bin/env python3
"""model.md §5-6: money model and farming, measured on the reference contract.

Money: for each rake level, run ranked fights between NPC-driven bots on a
fake chain and read the actual settlements. Reports player net per fight by
skill pairing, house/dev/share income per fight and refund frequency; asserts
conservation throughout.
Execution cost: the simulated fee model (chainsim.FeeModel) per fight, and the
stake at which the house's rake share pays for it, with the player's expected
value at each stake.
Farming: colluding fighters with distinct owners throw fights to pump one
rating; measures the rating a booster can gain per epoch and its QU cost under
the pair-start cap, the rematch gap and the known-owner exclusion.
Arena: with --arena LABEL=FILE (from scripts/combat-arena-metrics.py --json),
the demo-arena measurements are tabulated side by side.

  uv run python scripts/combat-economics.py --out docs/economics-report.md \
      --arena before=before.json --arena after=after.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import npcs  # noqa: E402
from qdojo.combat.chainsim import FeeModel  # noqa: E402
from qdojo.combat.codec import Op, decode_plan  # noqa: E402
from qdojo.combat.engine import resolve_round  # noqa: E402
from qdojo.combat.evaluate import ReaderPlanner  # noqa: E402
from qdojo.combat.contract import Manifest  # noqa: E402
from qdojo.combat.ledger import FeeProfile  # noqa: E402
from qdojo.combat.rules import candidate_1  # noqa: E402
from qdojo.combat.sim import World, commit_fields, identity, reveal_fields  # noqa: E402
from qdojo.combat.types import Action, Plan  # noqa: E402

RULES = candidate_1()
ADMIN, HOUSE, DEV, SHARE = (identity(x) for x in ("eco-admin", "eco-house", "eco-dev", "eco-share"))
STAKE = 1000


def manifest(rake_bps: int, ticks_per_epoch: int = 10_000) -> Manifest:
    fee = FeeProfile(1, rake_bps, 6000, 1000, 3000, HOUSE, DEV, SHARE)
    return Manifest(b"\xe0" * 32, b"\xe1" * 32, ADMIN, RULES, {1: (24, 12)}, {1: fee}, {1: STAKE},
                    ticks_per_epoch=ticks_per_epoch)


class Fighter:
    def __init__(self, w: World, label: str, policy, owner: str | None = None):
        self.w, self.policy = w, policy
        self.fid = identity("eco-fighter:" + label)
        self.owner = identity("eco-owner:" + (owner or label))
        w.owners[self.fid] = self.owner
        w.mint(self.owner, 10**9)
        w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=self.fid, registry_version=1, house_npc=0)
        w.send(self.owner, Op.REGISTER_FIGHTER, fighter_id=self.fid, registry_version=1)
        self.pending = {}
        self.spent = 0

    @property
    def f(self):
        return self.w.contract.fighters[self.fid]

    def step(self):
        w, c = self.w, self.w.contract
        f = self.f
        if f.lock == "IDLE" and w.tick >= f.cooldown_until:
            r = w.send(self.owner, Op.QUEUE_ENTER, STAKE, fighter_id=self.fid, auth_version=f.auth_version,
                       ruleset_digest=RULES.digest, timing_profile_id=1, fee_profile_id=1, tier_id=1,
                       max_gap=200, expires_tick=w.tick + 240)
            if r.ok:
                self.spent += STAKE
            return
        if f.lock != "CONTEST":
            return
        contest = c.contests[f.lock_ref]
        fight = c.fights[contest.fights[-1]]
        slot = fight.slot_of(self.fid)
        key = (fight.fight_id, fight.state.round_index)
        if fight.phase == "COMMIT" and fight.start_tick < w.tick <= fight.commit_last and slot not in fight.commits:
            me, opp = (fight.state.a, fight.state.b) if slot == "A" else (fight.state.b, fight.state.a)
            # This fight's public history: re-derive each revealed round from its plans.
            prior = tuple(resolve_round(RULES, r["start"], decode_plan(r["plans"]["A"]), decode_plan(r["plans"]["B"]))
                          for r in fight.rounds)
            other = "B" if slot == "A" else "A"
            history = tuple(tuple((b.a if other == "A" else b.b).effective for b in res.beats) for res in prior)
            obs = npcs.Observation(fight.state.round_index, me, opp, history, slot, prior)
            plan = self.policy(RULES, obs, npcs.Stream(self.fid, fight.fight_id, fight.state.round_index))
            salt = bytes((fight.fight_id * 7 + fight.state.round_index + i) % 256 for i in range(32))
            fields, salt = commit_fields(w, fight.fight_id, self.fid, self.owner, plan, salt)
            w.send(self.owner, Op.COMMIT, **fields)
            self.pending[key] = (plan, salt)
        elif fight.phase == "REVEAL" and slot not in fight.reveals and key in self.pending:
            plan, salt = self.pending[key]
            w.send(self.owner, Op.REVEAL, **reveal_fields(w, fight.fight_id, self.fid, plan, salt))


def run(w: World, fighters, ticks):
    for _ in range(ticks):
        for x in fighters:
            x.step()
        w.end()
    w.check_conservation()


def money(rake_levels, ticks):
    rows = []
    for rake in rake_levels:
        w = World(manifest(rake))
        w.mint(ADMIN, 10**9)
        strong = [Fighter(w, f"strong{i}-{rake}", ReaderPlanner()) for i in range(3)]
        weak = [Fighter(w, f"weak{i}-{rake}", npcs.mixed_v1) for i in range(3)]
        everyone = strong + weak
        run(w, everyone, ticks)
        c = w.contract
        done = [x for x in c.contests.values() if x.status == "DONE"]
        refunds = sum(1 for x in done if x.result.get("winner") is None)
        credits = c.ledger.credits

        def net(group):
            return sum(credits.get(x.owner, 0) + 0 for x in group) - sum(x.spent for x in group) \
                + sum(STAKE for x in group if x.f.lock == "QUEUED")
        fights = max(1, len(done))
        # Execution cost of the fights themselves: two entries per contest, the
        # commits and reveals actually sent, and the resolved rounds (tick costs
        # are shared by every fight running at once; the arena measures them).
        fees = FeeModel()
        sent = sum(1 for r in w.journal if r["k"] == "call" and r["frame"][8:12] in ("0700", "0800"))
        rounds = sum(len(f.rounds) for f in c.fights.values())
        exec_cost = (fees.per_call * (2 * len(done) + sent) + fees.per_resolved_round * rounds) / fights
        rows.append({"exec_per_fight": exec_cost,
            "rake_bps": rake, "contests": len(done), "refund_share": refunds / fights,
            "house_per_fight": credits.get(HOUSE, 0) / fights, "dev_per_fight": credits.get(DEV, 0) / fights,
            "share_per_fight": credits.get(SHARE, 0) / fights,
            "strong_net_per_fight": net(strong) / fights, "weak_net_per_fight": net(weak) / fights,
            "rake_per_fight": (credits.get(HOUSE, 0) + credits.get(DEV, 0) + credits.get(SHARE, 0)) / fights,
        })
    return rows


def thrower(rules, obs, rng):
    return Plan.of([Action.RECOVER] * 6)


def farming(epochs, ticks_per_epoch=2000):
    """One booster and N accomplices with distinct owners who always RECOVER."""
    out = []
    for accomplices in (1, 3, 6):
        w = World(manifest(500, ticks_per_epoch))
        w.mint(ADMIN, 10**9)
        booster = Fighter(w, f"booster-{accomplices}", npcs.ROSTER["kicker-v1"].policy)
        crew = [Fighter(w, f"acc{i}-{accomplices}", thrower) for i in range(accomplices)]
        same_owner = Fighter(w, f"sameowner-{accomplices}", thrower, owner=f"booster-{accomplices}")
        run(w, [booster, same_owner] + crew, epochs * ticks_per_epoch)
        c = w.contract
        paired_same = sum(1 for x in c.contests.values()
                          if {x.a.fighter_id, x.b.fighter_id} == {booster.fid, same_owner.fid})
        # Every fight here involves the ring, so the ring's net QU cost is exactly the rake it paid.
        rake_paid = sum(c.ledger.credits.get(x, 0) for x in (HOUSE, DEV, SHARE))
        out.append({"accomplices": accomplices, "epochs": epochs, "booster_rating": booster.f.lifetime,
                    "rating_gain_per_epoch": (booster.f.lifetime - 1000) / epochs,
                    "fights": booster.f.placement, "same_owner_pairings": paired_same,
                    "ring_qu_cost": rake_paid})
    return out


def break_even(exec_per_fight: float, rake_bps=500, house_bps=6000, stakes=(1000, 2500, 5000, 10000, 20000)):
    """House net per ranked fight and the player's expected value by stake."""
    r = rake_bps / 10_000
    rows = []
    for stake in stakes:
        house = 2 * stake * rake_bps // 10_000 * house_bps // 10_000
        rows.append({"stake": stake, "house": house, "exec": exec_per_fight, "net": house - exec_per_fight,
                     "ev": {p: stake * (2 * p * (1 - r) - 1) for p in (0.45, 0.50, 0.55, 0.60)}})
    return rows, 1 / (2 * (1 - r)), exec_per_fight / (2 * r * house_bps / 10_000)


def arena_tables(runs: list[tuple[str, dict]]) -> list[str]:
    """Demo-arena measurements side by side (combat-arena-metrics.py --json)."""
    if not runs:
        return []
    labels = [label for label, _ in runs]
    head = "| Measure | " + " | ".join(labels) + " |"
    sep = "|---|" + "---:|" * len(labels)

    def row(name, fn):
        vals = []
        for _, r in runs:
            try:
                v = fn(r)
            except (KeyError, TypeError, IndexError, ZeroDivisionError):
                v = None
            vals.append("n/a" if v is None else v)
        return f"| {name} | " + " | ".join(str(v) for v in vals) + " |"

    def ev(r, bucket):
        b = next((v for k, v in r["ev_by_strength"].items() if k.startswith(bucket)), None)
        return None if b is None else f"{b['net_per_fight']:+.0f} ({b['fighters']})"

    def season_line(r):
        return "; ".join(f"S{x['season']} {x['champion'] or x['status']} (rank {x['champion_lifetime_rank']}, "
                         f"top-3 qualified {sum(x['top3_qualified'])}/3)" for x in r["seasons"]) or "none final"
    lines = [head, sep,
             row("Ticks / fights (ranked, duel, cup)", lambda r: f"{r['ticks']} / {r['fights']} "
                 f"({r['fights_by_mode'].get('ranked', 0)}, {r['fights_by_mode'].get('duel', 0)}, "
                 f"{r['fights_by_mode'].get('cup', 0)})"),
             row("Tier-1 stake", lambda r: r.get("tier_stake", 1000)),
             row("House rake share per fight", lambda r: r["money"]["house_rake_per_fight"]),
             row("Execution fees per fight", lambda r: r["money"]["exec_per_fight"]),
             row("Sponsorship paid", lambda r: f"{r['money']['sponsorship_paid']:,}"),
             row("Market fees", lambda r: f"{r['money']['market_fees']:,}"),
             row("**House P&L per fight**", lambda r: f"**{r['money']['house_pnl_per_fight']:+.1f}**"),
             row("House net per ranked fight", lambda r: r["house_net_by_mode"]["ranked"]),
             row("House net per duel fight", lambda r: r["house_net_by_mode"]["duel"]),
             row("House net per cup fight (after sponsorship)", lambda r: r["house_net_by_mode"]["cup"]),
             row("EV per ranked fight, strong (score > 0.55)", lambda r: ev(r, "strong")),
             row("EV per ranked fight, average (0.45–0.55)", lambda r: ev(r, "average")),
             row("EV per ranked fight, weak (< 0.45)", lambda r: ev(r, "weak")),
             row("EV per ranked fight / stake, strong", lambda r: None if ev(r, "strong") is None else
                 f"{next(v for k, v in r['ev_by_strength'].items() if k.startswith('strong'))['net_per_fight'] / r.get('tier_stake', 1000):+.1%}"),
             row("Cups complete / top champion share", lambda r: f"{r['cups']['complete']} / "
                 f"{r['cups']['top'][0]} {r['cups']['top_share']:.0%}" if r["cups"]["top"] else r["cups"]["complete"]),
             row("Duel series / top winner share of series", lambda r: f"{r['duels']['series']} / "
                 f"{r['duels']['top'][0]} {r['duels']['top_share']:.0%}" if r["duels"]["top"] else r["duels"]["series"]),
             row("Rating range / stdev at the end", lambda r: f"{r['ratings']['final']['range']} / {r['ratings']['final']['stdev']}"),
             row("Mean rating drift per 1,000 ticks, last third", lambda r: r["ratings"]["mean_abs_drift_per_1000_ticks_last_third"]),
             row("Top-rated pair: meetings / share of their fights", lambda r: f"{r['matchmaking']['top_pair']['meetings']} / "
                 f"{r['matchmaking']['top_pair']['share_of_their_fights']:.0%}"),
             row("Most common ranked pair share", lambda r: f"{r['matchmaking']['most_common_pair_share']:.1%}"),
             row("Seasons", season_line),
             row("Market sales / median price", lambda r: f"{r['market']['sales']} / {r['market']['median_price']}"
                 if r.get("market") else None),
             row("index.json bytes", lambda r: f"{r['index_json_bytes']:,}")]
    return lines


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticks", type=int, default=6000)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--out", default=str(ROOT / "docs/economics-report.md"))
    p.add_argument("--arena", action="append", default=[], metavar="LABEL=FILE",
                   help="demo-arena measurements (combat-arena-metrics.py --json) to tabulate")
    p.add_argument("--notes", help="a Markdown file appended after the arena tables (findings, restart numbers)")
    a = p.parse_args()
    runs = [(x.split("=", 1)[0], json.loads(Path(x.split("=", 1)[1]).read_text())) for x in a.arena]
    m = money((0, 250, 500, 750, 1000), a.ticks)
    f = farming(a.epochs)
    measured = [r["money"]["exec_per_fight"] for _, r in runs if r["money"].get("exec_per_fight")]
    exec_fight = measured[-1] if measured else next(r["exec_per_fight"] for r in m if r["rake_bps"] == 500)
    tiers, be_score, be_stake = break_even(exec_fight)
    lines = [
        "# Combat candidate 1 — money and farming measurements", "",
        "Generated by `scripts/combat-economics.py` on the reference contract with fake QU; conservation "
        "asserted after every run. Bots: reader-v1 (stronger) and mixed-v1 (weaker), 1,000 QU stake. "
        "Execution fees come from the simulated fee model (`chainsim.FeeModel`: 10 QU per call, 1 per tick, "
        "20 per resolved round), a candidate, not a measured Qubic cost. Hosting and provider costs are not "
        "included.", "",
        "## Money by rake level", "",
        "| Rake bps | Contests | Refunded | Rake/fight | House/fight | Exec/fight | Dev/fight | Share/fight | "
        "Stronger net/fight | Weaker net/fight |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[f"| {r['rake_bps']} | {r['contests']} | {r['refund_share']:.1%} | {r['rake_per_fight']:.1f} | "
          f"{r['house_per_fight']:.1f} | {r['exec_per_fight']:.0f} | {r['dev_per_fight']:.1f} | {r['share_per_fight']:.1f} | "
          f"{r['strong_net_per_fight']:+.1f} | {r['weak_net_per_fight']:+.1f} |" for r in m], "",
        "Exec/fight counts the two entries, the commits and reveals sent and the resolved rounds; the ticks a "
        "fight shares with others add about 20 QU in the arena. At a 1,000 QU stake the house's rake share "
        "never covers it.", "",
        "Net per fight is per group of three fighters, divided by all contests. With no subsidy the players "
        "as a whole lose exactly the rake; skill moves QU from weaker to stronger bots. The game must not be "
        "promoted as guaranteed earnings.", "",
        "Every row stops at 30 contests: six fighters form 15 pairs, and the cap of two rated starts per pair "
        "per epoch allows exactly 30. With a small launch population, the pair cap rather than demand limits "
        "ranked volume: N fighters can play at most N(N-1) ranked fights per epoch.", "",
        "## Break-even stake", "",
        f"Execution cost per ranked fight: **{exec_fight:.0f} QU** "
        f"({'measured in the demo arena below' if measured else 'from the runs above, without tick costs'}). "
        f"At 500 bps rake and a 60% house share the house breaks even from a stake of **{be_stake:,.0f} QU**; "
        f"a player breaks even at a win share of **{be_score:.3f}** (draws refund).", "",
        "| Stake | House rake share/fight | Exec/fight | House net/fight | EV at 0.45 | EV at 0.50 | EV at 0.55 | EV at 0.60 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[f"| {t['stake']:,} | {t['house']} | {t['exec']:.0f} | {t['net']:+.0f} | "
          + " | ".join(f"{t['ev'][p]:+.0f}" for p in (0.45, 0.50, 0.55, 0.60)) + " |" for t in tiers], "",
        "EV is the player's net QU per fight at that win share with no draws. The demo arena's tier 1 is "
        "5,000 QU and tier 2 20,000 QU (docs/product-decisions.md).", "",
        "## Rating farming by a ring of throwers", "",
        "| Accomplices | Epochs | Booster rating | Gain/epoch | Rated fights | Same-owner pairings | Ring QU cost |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *[f"| {r['accomplices']} | {r['epochs']} | {r['booster_rating']} | {r['rating_gain_per_epoch']:+.0f} | "
          f"{r['fights']} | {r['same_owner_pairings']} | {r['ring_qu_cost']} |" for r in f], "",
        "The known-owner exclusion held (no same-owner pairing). Distinct-owner accomplices are not detectable "
        "by the contract: the pair cap (two rated starts per pair per epoch) and the 120-tick rematch gap bound "
        "the gain per accomplice, so a larger ring buys faster farming at a QU cost of the rake per thrown fight. "
        "These are mitigations, not sybil resistance (competition.md §3).",
    ]
    if runs:
        lines += ["", "## Demo arena measurements", "",
                  "Measured with `scripts/combat-arena-metrics.py`: the demo arena (`combat/live.py`) on the "
                  "simulated chain for a lineup like the public one, LLM planners replaced by mixed-v1 "
                  "(about their measured strength), tick_seconds 0. House P&L per fight is the house's rake share "
                  "plus market fees, minus execution fees and cup sponsorship paid, over every fight of every mode. "
                  "EV groups fighters by ranked score (at least 20 ranked fights).", "",
                  *arena_tables(runs)]
    if a.notes:
        lines += ["", Path(a.notes).read_text().rstrip()]
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
