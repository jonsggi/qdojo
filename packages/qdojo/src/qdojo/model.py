"""Offline model of the dojo's mechanics. House-side tooling, not part of
the developer API.

A cohort of archetypes (solve probability and latency per belt, entry
appetite) fights simulated rounds through the REAL evaluator
(`round.evaluate`), the REAL ladder (`belts.apply_settlement`) and the
same bond rules the house applies, so the money and the belts move exactly
as they would on chain. No chain, no LLM: a round costs microseconds, so
parameters can be swept and confidence intervals estimated.

What it answers: what a round costs the house, who ends up with the money,
how fast the ladder sorts fighters, how much a dominant bot can sweep, and
what bonds and podium do to all of that.
"""
import json
import random
import statistics
from dataclasses import dataclass, field

from . import hashing, payload, belts as B
from .round import RoundSpec, Observed, evaluate

BOND_EXPIRY_ROUNDS = 20


@dataclass
class Archetype:
    name: str
    solve: dict            # belt -> probability of a correct answer
    latency: dict          # belt -> (mean ticks, sd ticks) to commit when solving
    wrong_latency: float = 40.0
    enter: object = 1.0    # probability of sitting down when eligible; a number, or {belt: p} for a strategy
    count: int = 1
    house_funded: bool = False   # an NPC: the house tops it up before every round, at its own cost

    @staticmethod
    def from_dict(d):
        return Archetype(d["name"], d["solve"], {k: tuple(v) for k, v in d["latency"].items()},
                         d.get("wrong_latency", 40.0), d.get("enter", 1.0), d.get("count", 1), d.get("house_funded", False))


DEFAULT_COHORT = [
    {"name": "specialist", "solve": {"white": 0.98, "yellow": 0.05, "orange": 0.0, "green": 0.0, "blue": 0.0},
     "latency": {"white": [8, 3], "yellow": [30, 10], "orange": [30, 10], "green": [30, 10], "blue": [30, 10]}, "count": 2},
    {"name": "llm", "solve": {"white": 0.9, "yellow": 0.7, "orange": 0.35, "green": 0.05, "blue": 0.3},
     "latency": {"white": [20, 8], "yellow": [30, 10], "orange": [45, 15], "green": [60, 20], "blue": [60, 20]}, "count": 4},
    {"name": "agent", "solve": {"white": 0.9, "yellow": 0.85, "orange": 0.8, "green": 0.9, "blue": 0.7},
     "latency": {"white": [25, 8], "yellow": [35, 10], "orange": [50, 15], "green": [40, 15], "blue": [70, 20]}, "count": 2},
    {"name": "evo", "solve": {"white": 0.7, "yellow": 0.5, "orange": 0.3, "green": 0.2, "blue": 0.1},
     "latency": {"white": [5, 2], "yellow": [6, 2], "orange": [15, 10], "green": [15, 10], "blue": [30, 10]}, "count": 3},
    {"name": "npc", "solve": {"white": 0.0, "yellow": 0.0, "orange": 0.0, "green": 0.0, "blue": 0.0},
     "latency": {"white": [10, 3], "yellow": [10, 3], "orange": [10, 3], "green": [10, 3], "blue": [10, 3]}, "count": 3,
     "house_funded": True},
]


@dataclass
class Params:
    rounds: int = 200
    belts: tuple = ("white", "yellow", "orange", "green", "blue")
    entry_fee: int = 1000
    seed_cap: int = 5000
    match_bps: int = 10000
    rake_bps: int = 0
    rake_house_bps: int = 10000
    rake_dev_bps: int = 0
    rake_share_bps: int = 0
    payout_mode: int = payload.MODE_PODIUM
    bond_bps: int = 5000
    bond_rounds: int = 3
    min_players: int = 3
    ladder: bool = True
    commit_window: int = 300
    reveal_window: int = 120
    start_balance: int = 20000
    npc_rounds: int = 3        # house tops NPCs up to this many stakes before each round
    gate: str = "strict"       # strict: own belt or above | soft: one belt below allowed | handicap: any table, stake x 2^gap below
    season: int = 0            # reset the ladder every N rounds (0 = never)


@dataclass
class Fighter:
    identity: str
    arch: Archetype
    balance: int
    staked: int = 0
    earned: int = 0
    bonds: list = field(default_factory=list)


def _enter_p(arch, belt):
    e = arch.enter
    return e.get(belt, 0.0) if isinstance(e, dict) else float(e)


def _ident(i):
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    s = ""
    n = i
    for _ in range(60):
        s += letters[n % 26]
        n = n * 7 + 3
    return s


def simulate(params: Params, cohort: list[Archetype], rng: random.Random) -> dict:
    fighters = []
    k = 0
    for a in cohort:
        for _ in range(a.count):
            fighters.append(Fighter(_ident(k), a, params.start_balance)); k += 1
    by_id = {f.identity: f for f in fighters}
    belt_state, carry, house = {}, 0, 0
    house_cost, pots, rounds_played, void_rounds = [], [], 0, 0
    belt_hist, promotions, demotions = [], 0, 0
    per_round_top = []
    HOUSE = "H" * 60
    dojo_salt, answer = b"\x0d" * 16, "42"
    npc_funding_total, void_reasons = 0, {"no_quorum": 0}
    dev_take, share_take = 0, 0
    for r in range(1, params.rounds + 1):
        belt = params.belts[(r - 1) % len(params.belts)]
        rank = B.RANKS[belt]
        for f in fighters:
            if f.arch.house_funded:
                need = params.entry_fee * params.npc_rounds - f.balance
                if need > 0:
                    f.balance += need; house -= need; npc_funding_total += need
        if params.season and r % params.season == 1 and r > 1:
            belt_state.clear()
        def stake_for(f):
            gap = B.rank_of(belt_state, f.identity) - rank
            return params.entry_fee * (2 ** gap if params.gate == "handicap" and gap > 0 else 1)
        def allowed(f):
            if not params.ladder or params.gate == "handicap":
                return True
            gap = B.rank_of(belt_state, f.identity) - rank
            return gap <= (1 if params.gate == "soft" else 0)
        eligible = [f for f in fighters if allowed(f) and f.balance >= stake_for(f) and rng.random() < _enter_p(f.arch, belt)]
        if len(eligible) < params.min_players:
            void_rounds += 1
            continue
        publish = 1000
        spec = RoundSpec(r, publish, params.entry_fee, params.commit_window, params.reveal_window, b"\x11" * 32,
                         hashing.answer_commitment(r, dojo_salt, answer), "integer", params.seed_cap, params.rake_bps,
                         params.payout_mode, params.match_bps, carry, lobby_tick=900, lobby_window=50,
                         min_players=params.min_players, belt_rank=rank if (params.ladder and params.gate == "strict") else None,
                         bond_bps=params.bond_bps, bond_rounds=params.bond_rounds,
                         house_fighters=tuple(f.identity for f in fighters if f.arch.house_funded),
                         rake_house_bps=params.rake_house_bps, rake_dev_bps=params.rake_dev_bps,
                         rake_share_bps=params.rake_share_bps)
        obs, n = [], 0
        for f in eligible:
            n += 1
            obs.append(Observed(910, f"e{r}_{n:04d}", f.identity, HOUSE, stake_for(f), payload.INPUT_TYPE,
                                payload.encode(payload.Enter(r))))
            solved = rng.random() < f.arch.solve[belt]
            mean, sd = f.arch.latency[belt]
            lat = max(1, int(rng.gauss(mean, sd))) if solved else int(f.arch.wrong_latency)
            if lat > params.commit_window:
                continue  # too slow: no commit, seat forfeited
            ans = answer if solved else "1"
            salt = b"\x01" * 16
            c = hashing.player_commitment(r, f.identity, salt, ans)
            obs.append(Observed(publish + lat, f"c{r}_{n:04d}", f.identity, HOUSE, 0, payload.INPUT_TYPE,
                                payload.encode(payload.Commit(r, c))))
            obs.append(Observed(spec.reveal_start + 5, f"r{r}_{n:04d}", f.identity, HOUSE, 0, payload.INPUT_TYPE,
                                payload.encode(payload.Reveal(r, salt, ans))))
        ev = evaluate(spec, obs, HOUSE, dojo_salt, answer, final=True, belts=belt_state)
        rounds_played += 1
        if not any(not f.arch.house_funded for f in eligible):
            void_reasons["dead_table"] = void_reasons.get("dead_table", 0) + 1
        # money
        for e in ev.entries:
            if e.verdict in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal"):
                by_id[e.identity].balance -= e.stake; by_id[e.identity].staked += e.stake
        for p in ev.payouts:
            if p.kind == "win":
                by_id[p.identity].balance += p.amount; by_id[p.identity].earned += p.amount
        # bonds: hold, release, forfeit
        fought = {e.identity for e in ev.entries if e.verdict in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal")}
        forfeited = 0
        for f in fighters:
            for b in f.bonds:
                if b.get("done"):
                    continue
                if f.identity in fought and b["round"] < r:
                    b["fought"] += 1
                if b["fought"] >= params.bond_rounds:
                    b["done"] = "released"; f.balance += b["amount"]; f.earned += b["amount"]
                elif r - b["round"] >= BOND_EXPIRY_ROUNDS:
                    b["done"] = "forfeited"; forfeited += b["amount"]
        for bd in ev.bonds:
            by_id[bd.identity].bonds.append({"round": r, "amount": bd.amount, "fought": 0})
        cost = ev.seed_used - carry          # the house's own money into this pot
        house -= cost; house += ev.rake_split.get("house", ev.rake)
        dev_take += ev.rake_split.get("dev", 0); share_take += ev.rake_split.get("shareholders", 0)
        carry = ev.carry + forfeited
        npc_stakes = sum(e.stake for e in ev.entries if by_id[e.identity].arch.house_funded
                         and e.verdict in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal"))
        house_cost.append(cost - ev.rake + npc_stakes)   # NPC stakes are house money passing through the pot
        pots.append(ev.pot)
        if params.ladder:
            ch = B.apply_settlement(belt_state, rank, ev.entries)
            promotions += sum(1 for c in ch if c.after > c.before)
            demotions += sum(1 for c in ch if c.after < c.before)
        if ev.payouts:
            top = max((p.amount for p in ev.payouts if p.kind == "win"), default=0)
            per_round_top.append(top / max(1, ev.pot))
        if r % 25 == 0:
            belt_hist.append({"round": r, "belts": {a.name: [B.rank_of(belt_state, f.identity) for f in fighters if f.arch is a] for a in cohort}})
    nets = sorted(f.earned - f.staked for f in fighters)
    total_earn = sum(f.earned for f in fighters) or 1
    by_arch = {}
    for a in cohort:
        fs = [f for f in fighters if f.arch is a]
        by_arch[a.name] = {"count": len(fs),
                           "net_per_round": round(sum(f.earned - f.staked for f in fs) / len(fs) / max(1, rounds_played), 1),
                           "earned_share": round(sum(f.earned for f in fs) / total_earn, 3),
                           "final_belts": [B.belt_name(B.rank_of(belt_state, f.identity)) for f in fs],
                           "broke": sum(1 for f in fs if f.balance < params.entry_fee)}
    return {"rounds_played": rounds_played, "void_rounds": void_rounds, "dead_tables": void_reasons.get("dead_table", 0),
            "house_cost_per_round": round(sum(house_cost) / max(1, len(house_cost)), 1),
            "npc_funding_per_round": round(npc_funding_total / max(1, rounds_played), 1),
            "house_total": house, "dev_take": dev_take, "share_take": share_take,
            "house_net_per_round": round(house / max(1, rounds_played), 1),
            "avg_pot": round(statistics.mean(pots), 1) if pots else 0,
            "top_share_of_pot": round(statistics.mean(per_round_top), 3) if per_round_top else None,
            "gini_net": round(_gini([n - min(nets) for n in nets]), 3) if nets else None,
            "max_fighter_share_of_earnings": round(max(f.earned for f in fighters) / total_earn, 3),
            "promotions": promotions, "demotions": demotions, "by_archetype": by_arch,
            "bonds_open": sum(1 for f in fighters for b in f.bonds if not b.get("done")),
            "bonds_forfeited": sum(b["amount"] for f in fighters for b in f.bonds if b.get("done") == "forfeited"),
            "belt_history": belt_hist}


def _gini(xs):
    xs = sorted(xs); n = len(xs); s = sum(xs)
    if n == 0 or s == 0:
        return 0.0
    return round((2 * sum((i + 1) * x for i, x in enumerate(xs)) / (n * s)) - (n + 1) / n, 4)


def run(params: Params, cohort_spec=None, replicates: int = 10, seed: int = 1) -> dict:
    cohort = [Archetype.from_dict(d) for d in (cohort_spec or DEFAULT_COHORT)]
    runs = [simulate(params, cohort, random.Random(seed + i)) for i in range(replicates)]
    def agg(key):
        vals = [r[key] for r in runs if r[key] is not None]
        if not vals:
            return None
        m = statistics.mean(vals)
        ci = 1.96 * statistics.stdev(vals) / (len(vals) ** 0.5) if len(vals) > 1 else 0
        return {"mean": round(m, 2), "ci95": round(ci, 2)}
    out = {"params": vars(params) | {"payout_mode": payload.MODE_NAMES[params.payout_mode]}, "replicates": replicates,
           "house_cost_per_round": agg("house_cost_per_round"), "npc_funding_per_round": agg("npc_funding_per_round"),
           "house_net_per_round": agg("house_net_per_round"), "dev_take": agg("dev_take"), "share_take": agg("share_take"),
           "avg_pot": agg("avg_pot"),
           "top_share_of_pot": agg("top_share_of_pot"), "gini_net": agg("gini_net"),
           "max_fighter_share_of_earnings": agg("max_fighter_share_of_earnings"),
           "promotions": agg("promotions"), "demotions": agg("demotions"), "void_rounds": agg("void_rounds"),
           "dead_tables": agg("dead_tables"),
           "bonds_forfeited": agg("bonds_forfeited"),
           "by_archetype": {}}
    for name in runs[0]["by_archetype"]:
        out["by_archetype"][name] = {
            "net_per_round": round(statistics.mean(r["by_archetype"][name]["net_per_round"] for r in runs), 1),
            "earned_share": round(statistics.mean(r["by_archetype"][name]["earned_share"] for r in runs), 3),
            "broke": round(statistics.mean(r["by_archetype"][name]["broke"] for r in runs), 2),
            "final_belts": _belt_dist(sum((r["by_archetype"][name]["final_belts"] for r in runs), []))}
    out["belt_history"] = runs[0]["belt_history"]
    return out


def _belt_dist(names):
    d = {}
    for n in names:
        d[n] = d.get(n, 0) + 1
    tot = sum(d.values()) or 1
    return {k: round(v / tot, 2) for k, v in sorted(d.items(), key=lambda kv: B.RANKS[kv[0]])}


def calibrate(fighters_json: dict, min_rounds: int = 3, npcs: set | None = None) -> list[dict]:
    """Archetypes measured from a live fighters.json: one per named fighter
    with enough rounds, solve probability and mean latency per belt.

    `npcs` is the set of house-funded IDENTITIES (the same list the house
    tops up). Names are player-chosen and untrusted: the "NPC" prefix is
    used only when no list is given, and only for an offline model."""
    out = []
    for f in fighters_json.get("fighters", []):
        if f.get("rounds_played", 0) < min_rounds:
            continue
        solve, lat = {}, {}
        for b in B.BELTS:
            bb = f.get("by_belt", {}).get(b)
            solve[b] = round(bb["solved"] / bb["rounds"], 2) if bb and bb["rounds"] else 0.0
            lat[b] = [bb["avg_solve_ticks"] or 30, max(3, (bb["avg_solve_ticks"] or 30) * 0.3)] if bb else [30, 10]
        name = f.get("name") or f["identity"][:8]
        funded = (f["identity"] in npcs) if npcs is not None else name.upper().startswith("NPC")
        out.append({"name": name, "solve": solve, "latency": lat, "count": 1, "house_funded": funded})
    return out


def sweep(base: Params, grid: dict, cohort_spec=None, replicates: int = 5, seed: int = 1) -> list[dict]:
    """grid: {"match_bps": [0, 5000, 10000], "gate": ["strict", "soft"]} -> one result per combination."""
    import itertools
    keys = list(grid)
    results = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = Params(**{**vars(base), **dict(zip(keys, combo))})
        r = run(p, cohort_spec, replicates, seed)
        results.append({"combo": dict(zip(keys, combo)), "house_cost_per_round": r["house_cost_per_round"]["mean"],
                        "top_share_of_pot": (r["top_share_of_pot"] or {}).get("mean"), "gini_net": r["gini_net"]["mean"],
                        "max_fighter_share": r["max_fighter_share_of_earnings"]["mean"],
                        "promotions": r["promotions"]["mean"], "void_rounds": r["void_rounds"]["mean"],
                        "dead_tables": r["dead_tables"]["mean"],
                        "by_archetype": {k: v["net_per_round"] for k, v in r["by_archetype"].items()}})
    return results
