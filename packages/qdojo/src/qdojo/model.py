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

from . import hashing, payload, belts as B, fees
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
    gate: str = "strict"       # strict: own belt or above | soft: one belt below | handicap: any table, stake x 2^gap | sensei: any table, but below your belt you win back at most your stake and earn no points
    season: int = 0            # reset the ladder every N rounds (0 = never)
    fee_mode: str = "fixed"    # fixed: entry_fee at every table | auto: the per-belt controller (fees.py)
    fee_alpha: float = 0.5     # auto: fee' = fee * (occ / tgt) ** alpha
    fee_window: int = 8        # auto: settled or void rounds at the belt that count
    fee_headroom: int = 2      # auto: tgt = min_players + headroom
    fee_clamp: float = 1.5     # auto: one retarget moves the fee by at most this factor
    fee_floor: int = 100       # auto: absolute floor in QU
    fee_start: int = 1000      # auto: the fee at a belt with no history yet
    fee_cap: int = 0           # auto: an absolute ceiling in QU (0 = none); the only ceiling without a rake
    fee_settled_only: bool = False   # auto: retarget from settled rounds only (default: void rounds count too)
    refill: bool = False       # owners top a broke fighter back up to start_balance (their money, not the house's)
    demand: str = "none"       # none: every eligible fighter sits down at any price | ev: only when its own expected value is >= 0
    target_pot: int = 0        # corollary: seed_cap = max(0, target_pot - tgt * last fee at the belt); 0 = the fixed seed_cap
    target_pot_taper: int = 0  # rounds over which target_pot declines linearly to 0 (0 = constant)


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
    policy = fees.FeePolicy(params.fee_alpha, params.fee_window, params.fee_headroom, params.fee_clamp,
                            params.fee_floor, params.fee_start, params.fee_cap) if params.fee_mode == "auto" else None
    owner_funding = 0
    tgt = max(1, params.min_players + params.fee_headroom)
    rho, m = params.rake_bps / 10000, params.match_bps / 10000
    real = [a for a in cohort if not a.house_funded] or cohort
    p_bar = {b: sum(a.solve[b] * a.count for a in real) / sum(a.count for a in real) for b in params.belts}
    fee_rows, seed_retired = [], None
    fee_hist, cap_hist, subsidy, fstar_hist, occ_hist = ({b: [] for b in params.belts} for _ in range(5))
    for r in range(1, params.rounds + 1):
        belt = params.belts[(r - 1) % len(params.belts)]
        rank = B.RANKS[belt]
        # what this table announces: the fee (fixed, or retargeted from the belt's own
        # history) and the seed cap (fixed, or the corollary's top-up to a target pot)
        prev_fee = fees.last_fee(fee_rows, belt, policy.start if policy else params.entry_fee)
        if params.target_pot:
            tp = params.target_pot * max(0.0, 1 - (r - 1) / params.target_pot_taper) if params.target_pot_taper else params.target_pot
            seed_cap = max(0, int(tp - tgt * prev_fee))
        else:
            seed_cap = params.seed_cap
        if policy:
            rows = [x for x in fee_rows if x["state"] == "settled"] if params.fee_settled_only else fee_rows
            d = fees.next_fee(rows, belt, policy, params.min_players, seed_cap, params.rake_bps)
            fee = d["fee"]
            if d["f_star"] is not None:
                subsidy[belt].append(d["f_star"] - fee); fstar_hist[belt].append(d["f_star"])
        else:
            fee = params.entry_fee
        fee_hist[belt].append(fee); cap_hist[belt].append(seed_cap)
        if seed_retired is None and all(c and c[-1] == 0 for c in cap_hist.values()):
            seed_retired = r
        for f in fighters:
            if f.arch.house_funded:
                need = fee * params.npc_rounds - f.balance
                if need > 0:
                    f.balance += need; house -= need; npc_funding_total += need
            elif params.refill and f.balance < fee:
                owner_funding += params.start_balance - f.balance; f.balance = params.start_balance
        if params.season and r % params.season == 1 and r > 1:
            belt_state.clear()
        def stake_for(f):
            gap = B.rank_of(belt_state, f.identity) - rank
            return fee * (2 ** gap if params.gate == "handicap" and gap > 0 else 1)
        def allowed(f):
            if not params.ladder or params.gate in ("handicap", "sensei"):
                return True
            gap = B.rank_of(belt_state, f.identity) - rank
            return gap <= (1 if params.gate == "soft" else 0)

        def is_sensei(f):
            return params.gate == "sensei" and params.ladder and B.rank_of(belt_state, f.identity) > rank

        def wants(f):
            """Sits down? Under `ev` demand a fighter enters only when its own
            expected value at the announced fee is non-negative: it solves with
            its calibrated probability and shares the winners' pot with the
            other expected solvers at a table of `tgt`. House fighters sit
            regardless (they are paid to). A sensei can win back at most its
            stake, so it sits only while it has a bond to release."""
            if rng.random() >= _enter_p(f.arch, belt):
                return False
            if params.demand != "ev" or f.arch.house_funded:
                return True
            if is_sensei(f):
                return any(not b.get("done") for b in f.bonds)
            stake = stake_for(f)
            winners_pot = (min(seed_cap, int(tgt * stake * m)) + carry + tgt * stake) * (1 - rho)
            return f.arch.solve[belt] * winners_pot / (1 + p_bar[belt] * (tgt - 1)) >= stake
        eligible = [f for f in fighters if allowed(f) and f.balance >= stake_for(f) and wants(f)]
        occ_hist[belt].append(len(eligible))
        fee_rows.append({"round_id": r, "belt": belt, "entrants": len(eligible), "entry_fee": fee,
                         "state": "settled" if len(eligible) >= params.min_players else "void"})
        if len(eligible) < params.min_players:
            void_rounds += 1
            continue
        publish = 1000
        spec = RoundSpec(r, publish, fee, params.commit_window, params.reveal_window, b"\x11" * 32,
                         hashing.answer_commitment(r, dojo_salt, answer), "integer", seed_cap, params.rake_bps,
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
        senseis = {f.identity for f in eligible if is_sensei(f)}
        if senseis:
            excess = 0
            for p in ev.payouts:
                if p.kind == "win" and p.identity in senseis:
                    stake = next((e.stake for e in ev.entries if e.identity == p.identity), 0)
                    if p.amount > stake:
                        excess += p.amount - stake; p.amount = stake
            others = [p for p in ev.payouts if p.kind == "win" and p.identity not in senseis]
            if others and excess:
                each = excess // len(others)
                for p in others:
                    p.amount += each
                ev.carry += excess - each * len(others)
            else:
                ev.carry += excess
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
            movers = [e for e in ev.entries if e.identity not in senseis]
            ch = B.apply_settlement(belt_state, rank, movers)
            promotions += sum(1 for c in ch if c.after > c.before)
            demotions += sum(1 for c in ch if c.after < c.before)
        if ev.payouts:
            top = max((p.amount for p in ev.payouts if p.kind == "win"), default=0)
            per_round_top.append(top / max(1, ev.pot))
        if r % 25 == 0:
            belt_hist.append({"round": r, "belts": {a.name: [B.rank_of(belt_state, f.identity) for f in fighters if f.arch is a] for a in cohort}})
    nets = sorted(f.earned - f.staked for f in fighters)
    total_earn = sum(f.earned for f in fighters) or 1
    cheapest = min((h[-1] for h in fee_hist.values() if h), default=params.entry_fee)
    by_arch = {}
    for a in cohort:
        fs = [f for f in fighters if f.arch is a]
        by_arch[a.name] = {"count": len(fs),
                           "net_per_round": round(sum(f.earned - f.staked for f in fs) / len(fs) / max(1, rounds_played), 1),
                           "earned_share": round(sum(f.earned for f in fs) / total_earn, 3),
                           "final_belts": [B.belt_name(B.rank_of(belt_state, f.identity)) for f in fs],
                           "broke": sum(1 for f in fs if f.balance < cheapest)}
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
            "fees": {b: _fee_stats(h, occ_hist[b]) for b, h in fee_hist.items()},
            "f_star_range": {b: ([min(x), max(x)] if x else None) for b, x in fstar_hist.items()},
            "subsidy_per_seat": {b: (round(statistics.mean(x), 1) if x else None) for b, x in subsidy.items()},
            "seed_cap_final": {b: (c[-1] if c else None) for b, c in cap_hist.items()},
            "seed_retired_round": seed_retired,
            "owner_funding_per_round": round(owner_funding / max(1, rounds_played), 1),
            "belt_history": belt_hist}


def _fee_stats(series, entrants=(), tail=20):
    """The fee a belt charged over the run, who sat down at it, and whether
    its last `tail` tables settled or oscillated: reversals counts direction
    changes, spread is max/min over the tail."""
    if not series:
        return {"series": [], "entrants": [], "final": None, "mean": None, "reversals": 0, "spread": None}
    last = series[-tail:]
    diffs = [b - a for a, b in zip(last, last[1:]) if b != a]
    reversals = sum(1 for a, b in zip(diffs, diffs[1:]) if (a > 0) != (b > 0))
    return {"series": series, "entrants": list(entrants), "final": series[-1], "mean": round(statistics.mean(series), 1),
            "reversals": reversals, "spread": round(max(last) / max(1, min(last)), 3)}


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
    def agg_by_belt(key, sub=None):
        res = {}
        for b in runs[0][key]:
            vals = [(r[key][b][sub] if sub else r[key][b]) for r in runs]
            vals = [v for v in vals if v is not None]
            res[b] = round(statistics.mean(vals), 2) if vals else None
        return res
    out["fees"] = {b: {"final": agg_by_belt("fees", "final")[b], "mean": agg_by_belt("fees", "mean")[b],
                       "reversals": agg_by_belt("fees", "reversals")[b], "spread": agg_by_belt("fees", "spread")[b]}
                   for b in runs[0]["fees"]}
    out["subsidy_per_seat"] = agg_by_belt("subsidy_per_seat")
    out["seed_cap_final"] = agg_by_belt("seed_cap_final")
    retired = [r["seed_retired_round"] for r in runs if r["seed_retired_round"] is not None]
    out["seed_retired_round"] = round(statistics.mean(retired), 1) if retired else None
    out["fee_trajectory"] = {b: runs[0]["fees"][b]["series"] for b in runs[0]["fees"]}
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
                        "fee_final": {b: v["final"] for b, v in r["fees"].items()},
                        "fee_reversals": {b: v["reversals"] for b, v in r["fees"].items()},
                        "subsidy_per_seat": r["subsidy_per_seat"], "seed_retired_round": r["seed_retired_round"],
                        "by_archetype": {k: v["net_per_round"] for k, v in r["by_archetype"].items()}})
    return results
