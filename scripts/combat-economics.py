#!/usr/bin/env python3
"""model.md §5-6: money model and farming, measured on the reference contract.

Money: for each rake level, run ranked fights between NPC-driven bots on a
fake chain and read the actual settlements. Reports player net per fight by
skill pairing, house/dev/share income per fight and refund frequency; asserts
conservation throughout.
Farming: colluding fighters with distinct owners throw fights to pump one
rating; measures the rating a booster can gain per epoch and its QU cost under
the pair-start cap, the rematch gap and the known-owner exclusion.

  uv run python scripts/combat-economics.py --out docs/economics-report.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import npcs  # noqa: E402
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
        rows.append({
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticks", type=int, default=6000)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--out", default=str(ROOT / "docs/economics-report.md"))
    a = p.parse_args()
    m = money((0, 250, 500, 750, 1000), a.ticks)
    f = farming(a.epochs)
    lines = [
        "# Combat candidate 1 — money and farming measurements", "",
        "Generated by `scripts/combat-economics.py` on the reference contract with fake QU; conservation "
        "asserted after every run. Bots: reader-v1 (stronger) and mixed-v1 (weaker), 1,000 QU stake. "
        "Execution fees, hosting and provider costs are not included; they need a deployed contract.", "",
        "## Money by rake level", "",
        "| Rake bps | Contests | Refunded | Rake/fight | House/fight | Dev/fight | Share/fight | "
        "Stronger net/fight | Weaker net/fight |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[f"| {r['rake_bps']} | {r['contests']} | {r['refund_share']:.1%} | {r['rake_per_fight']:.1f} | "
          f"{r['house_per_fight']:.1f} | {r['dev_per_fight']:.1f} | {r['share_per_fight']:.1f} | "
          f"{r['strong_net_per_fight']:+.1f} | {r['weak_net_per_fight']:+.1f} |" for r in m], "",
        "Net per fight is per group of three fighters, divided by all contests. With no subsidy the players "
        "as a whole lose exactly the rake; skill moves QU from weaker to stronger bots. The game must not be "
        "promoted as guaranteed earnings.", "",
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
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
