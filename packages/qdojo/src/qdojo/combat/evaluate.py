"""Strategic validation harness (docs/model.md §2).

Paired, side-swapped trials with frozen seeds; per-opponent scores with a
paired-bootstrap 95% lower bound; fight-shape metrics. The policies here are
evaluation instruments (spam, cycles, stalling, best-response search), not
the disclosed practice roster in npcs.py.

Floating point appears only in reporting statistics, never in combat.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Callable

from ..hashing import sha256
from . import npcs
from .engine import resolve_beat, resolve_round
from .rules import Ruleset, candidate_1
from .training import Contestant, run_fight
from .types import ATTACKS, NO_POWER, SUBMITTED, Action, FightState, Plan

J, K, B, D, T, R = Action.JAB, Action.KICK, Action.BLOCK, Action.DUCK, Action.THROW, Action.RECOVER
TAG_EVAL = b"qdojo/combat/eval/v1\0"


# ---- evaluation policies ---------------------------------------------------

def spam(action: Action, spend_power_round: int | None = None):
    return pattern([action] * 6, spend_power_round)


def pattern(actions, spend_power_round: int | None = 2):
    actions = tuple(actions)

    def policy(rules, obs, rng):
        slot = NO_POWER
        if spend_power_round is not None and obs.round_index == spend_power_round and obs.self_state.power_available:
            slot = next((i for i, a in enumerate(actions) if a in ATTACKS), NO_POWER)
        return Plan.of(actions, slot)
    return policy


def repeat_last_winner(rules, obs, rng):
    """Round 0 mixed; then replay whichever side's plan lost less HP last round."""
    if not obs.prior:
        return npcs.mixed_v1(rules, obs, rng)
    last = obs.prior[-1]
    lost_a = last.start.a.hp - last.end.a.hp
    lost_b = last.start.b.hp - last.end.b.hp
    mine, theirs = (last.plan_a, last.plan_b) if obs.slot == "A" else (last.plan_b, last.plan_a)
    my_loss, their_loss = (lost_a, lost_b) if obs.slot == "A" else (lost_b, lost_a)
    chosen = mine if my_loss <= their_loss else theirs
    slot = chosen.power_slot if chosen.power_slot != NO_POWER and obs.self_state.power_available else NO_POWER
    return Plan.of(chosen.actions, slot)


def _sample_plans(rng: random.Random, n: int):
    return [tuple(rng.choice(SUBMITTED) for _ in range(6)) for _ in range(n)]


def _round_value(rules, me, opp, mine: Plan, theirs: Plan) -> int:
    """HP margin gained over one round, plus a small stamina term; KO dominates."""
    start = FightState(0, me, opp)
    res = resolve_round(rules, start, mine, theirs)
    a, b = res.beats[-1].a.after, res.beats[-1].b.after
    if b.hp == 0 and a.hp > 0:
        return 10_000
    if a.hp == 0 and b.hp > 0:
        return -10_000
    return 8 * ((a.hp - me.hp) - (b.hp - opp.hp)) + (a.stamina - b.stamina)


@dataclass
class SearchPlanner:
    """Bounded Monte-Carlo plan search: `candidates` random plans (plus
    mutations of the incumbent) scored against `samples` predicted opponent
    plans. History-aware when `use_history`; resource-aware unless
    `ignore_resources`, which plans as if both sides stood at the initial state
    (the ablation docs/model.md asks for)."""
    candidates: int = 160
    samples: int = 12
    use_history: bool = True
    ignore_resources: bool = False
    name: str = "search-v1"

    def __call__(self, rules: Ruleset, obs, stream) -> Plan:
        seed = bytes(stream.byte() for _ in range(16))
        rng = random.Random(seed)
        me, opp = obs.self_state, obs.opponent_state
        if self.ignore_resources:
            me = opp = npcs.FighterState.initial(rules)
        opp_plans = self._predict(rules, obs, rng)
        power_ok = obs.self_state.power_available and obs.round_index == rules.rounds - 1
        best, best_v = None, None
        pool = _sample_plans(rng, self.candidates) + [
            (J, J, J, R, J, J), (D, K, R, D, K, R), (B, T, R, D, J, R), (T, J, D, K, R, J)]
        for acts in pool:
            slot = NO_POWER
            if power_ok:
                slot = next((i for i, a in enumerate(acts) if a in ATTACKS), NO_POWER)
            plan = Plan.of(acts, slot)
            v = sum(_round_value(rules, me, opp, plan, o) for o in opp_plans)
            if best_v is None or v > best_v:
                best, best_v = plan, v
        return best

    def _predict(self, rules, obs, rng):
        """Opponent plan samples: their past plans in this fight if history is on,
        otherwise draws from a generic mixed policy."""
        out = []
        if self.use_history and obs.prior:
            for res in obs.prior:
                p = res.plan_b if obs.slot == "A" else res.plan_a
                out.append(Plan.of(p.actions))
        stream = npcs.Stream(bytes(rng.getrandbits(8) for _ in range(32)), 0, 0)
        generic = npcs.Observation(0, obs.opponent_state, obs.self_state)
        while len(out) < self.samples:
            p = npcs.mixed_v1(rules, generic, stream)
            out.append(Plan.of(p.actions))
        return out[: max(self.samples, len(out))]


def best_response_opening(rules: Ruleset, opponent: npcs.Policy, samples: int = 8,
                          limit: int | None = None) -> tuple[Plan, float]:
    """Enumerate every unpowered six-action opening (46,656) against `samples`
    round-0 plans of `opponent`. One-round search, not a solution of the game."""
    s0 = npcs.FighterState.initial(rules)
    obs = npcs.Observation(0, s0, s0)
    opp = [Plan.of(opponent(rules, obs, npcs.Stream(sha256(TAG_EVAL, b"br", bytes([i])), 0, 0)).actions)
           for i in range(samples)]
    best, best_v = None, None
    for n, acts in enumerate(itertools.product(SUBMITTED, repeat=6)):
        if limit is not None and n >= limit:
            break
        plan = Plan.of(acts)
        v = sum(_round_value(rules, s0, s0, plan, o) for o in opp)
        if best_v is None or v > best_v:
            best, best_v = plan, v
    return best, best_v / samples


def exploit_opening(opening: Plan, then: npcs.Policy = npcs.mixed_v1):
    def policy(rules, obs, rng):
        return opening if obs.round_index == 0 else then(rules, obs, rng)
    return policy


def pools() -> dict[str, dict[str, npcs.Policy]]:
    """Named opponent pools. 'baseline' is the model.md §2 exploit list."""
    roster = {n.id: n.policy for n in npcs.ROSTER.values()}
    spams = {f"spam-{a.name.lower()}": spam(a) for a in SUBMITTED}
    spams["spam-jab-spend-power"] = spam(J, 0)
    cycles = {f"cycle-{x.name.lower()}-{y.name.lower()}": pattern([x, y] * 3)
              for x, y in itertools.combinations(SUBMITTED, 2)}
    misc = {
        "repeat-last-winner": repeat_last_winner,
        "stall-guard": pattern([B, D, R, B, D, R], None),
        "fixed-recover-3-6": pattern([J, J, R, J, J, R]),
        "exhaust-throw": pattern([T] * 6, 0),
    }
    held_out_styles = {   # parameter variants withheld from any tuning
        "jabber-alt": pattern([J, J, R, J, J, J]),
        "kicker-alt": pattern([K, K, R, R, K, R]),
        "turtle-alt": pattern([B, R, B, D, B, R]),
        "thrower": pattern([T, R, T, D, T, R]),
    }
    return {
        "roster": roster,
        "baseline": {**roster, **spams, **cycles, **misc},
        "fixed-style": {k: roster[k] for k in ("jabber-v1", "turtle-v1", "kicker-v1")} | held_out_styles,
        "competent": {"mixed-v1": roster["mixed-v1"], "scout-v1": roster["scout-v1"],
                      "search-v1": SearchPlanner(), "repeat-last-winner": repeat_last_winner},
    }


def policy_by_name(name: str) -> npcs.Policy:
    if name in npcs.ROSTER:
        return npcs.ROSTER[name].policy
    if name == "search-v1":
        return SearchPlanner()
    if name == "search-blind":
        return SearchPlanner(use_history=False, name="search-blind")
    if name == "search-nores":
        return SearchPlanner(ignore_resources=True, name="search-nores")
    for pool in pools().values():
        if name in pool:
            return pool[name]
    raise KeyError(f"unknown policy {name!r}")


# ---- runner and statistics -------------------------------------------------

@dataclass
class Tally:
    scores: list[float] = field(default_factory=list)   # per seed: mean of the two swapped fights
    fights: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    reached_round_2: int = 0
    round0_ko: int = 0
    trailing_after_r0: int = 0
    trailing_won: int = 0
    exhausted_beats: int = 0
    executed_beats: int = 0
    power_used: int = 0
    power_wasted: int = 0
    openings_converted: int = 0
    hp_margin: int = 0


def _record(t: Tally, replay: dict, slot: str) -> float:
    other = "B" if slot == "A" else "A"
    out = replay["outcome"]
    score = 0.5 if out["winner"] is None else 1.0 if out["winner"] == slot else 0.0
    t.fights += 1
    t.wins += score == 1.0
    t.draws += score == 0.5
    t.losses += score == 0.0
    rounds = replay["rounds"]
    t.reached_round_2 += len(rounds) == 3
    first = rounds[0]
    if first["end"]["outcome"] and out["result"] in ("KO", "DOUBLE_KO"):
        t.round0_ko += 1
    elif len(rounds) > 1:
        ea, eb = first["end"]["A"]["hp"], first["end"]["B"]["hp"]
        if ea != eb:
            t.trailing_after_r0 += 1
            trailer = "A" if ea < eb else "B"
            t.trailing_won += out["winner"] == trailer
    for r in rounds:
        for beat in r["beats"]:
            me = beat[slot]
            reasons = me["reasons"]
            t.executed_beats += 1
            t.exhausted_beats += "INSUFFICIENT_STAMINA" in reasons
            t.power_used += "POWER_USED" in reasons
            t.power_wasted += "POWER_WASTED" in reasons
            t.openings_converted += "OPENING_USED" in reasons
    t.hp_margin += replay["final"][slot]["hp"] - replay["final"][other]["hp"]
    return score


def paired(x: npcs.Policy, y: npcs.Policy, seeds: int, suite: str, x_id="x", y_id="y",
           rules: Ruleset | None = None, first_seed: int = 0) -> Tally:
    """`seeds` paired trials; each plays twice with fighter slots swapped."""
    rules = rules or candidate_1()
    t = Tally()
    for n in range(first_seed, first_seed + seeds):
        seed = sha256(TAG_EVAL, suite.encode(), n.to_bytes(8, "little"))
        pair_score = 0.0
        for names in (("P", "Q"), ("Q", "P")):
            cx = Contestant(names[0], policy=x, policy_id=x_id)
            cy = Contestant(names[1], policy=y, policy_id=y_id)
            replay = run_fight(cx, cy, seed, n + 1, rules)
            slot = "A" if replay["fighters"]["A"]["name"] == names[0] else "B"
            pair_score += _record(t, replay, slot)
        t.scores.append(pair_score / 2)
    return t


def bootstrap_lower(scores: list[float], resamples: int = 2000, seed: int = 0) -> float:
    """Paired-bootstrap 2.5th percentile of the mean (deterministic resampling)."""
    if not scores:
        return float("nan")
    rng = random.Random(seed)
    n = len(scores)
    means = sorted(sum(scores[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def summarize(name: str, t: Tally) -> dict:
    trailing = t.trailing_won / t.trailing_after_r0 if t.trailing_after_r0 else float("nan")
    return {
        "opponent": name, "fights": t.fights, "W": t.wins, "D": t.draws, "L": t.losses,
        "score": mean(t.scores), "lower95": bootstrap_lower(t.scores),
        "draw_rate": t.draws / t.fights, "round2_rate": t.reached_round_2 / t.fights,
        "round0_ko_rate": t.round0_ko / t.fights, "trailing_after_r0_win_rate": trailing,
        "exhausted_rate": t.exhausted_beats / max(1, t.executed_beats),
        "power_used": t.power_used, "power_wasted": t.power_wasted,
        "openings_converted": t.openings_converted, "mean_hp_margin": t.hp_margin / t.fights,
    }


def evaluate(policy: npcs.Policy, pool: dict[str, npcs.Policy], seeds: int, suite: str = "test",
             policy_id: str = "policy", progress: Callable[[str], None] | None = None) -> list[dict]:
    rows = []
    for name, opp in pool.items():
        t = paired(policy, opp, seeds, f"{suite}/{name}", policy_id, name)
        rows.append(summarize(name, t))
        if progress:
            progress(f"{name}: score {rows[-1]['score']:.3f}")
    return rows


def ablation(full: npcs.Policy, ablated: npcs.Policy, pool: dict[str, npcs.Policy], seeds: int,
             suite: str = "ablation") -> dict:
    """Paired difference full-minus-ablated on identical seeds and opponents."""
    diffs = []
    for name, opp in pool.items():
        a = paired(full, opp, seeds, f"{suite}/{name}")
        b = paired(ablated, opp, seeds, f"{suite}/{name}")
        diffs += [x - y for x, y in zip(a.scores, b.scores)]
    return {"mean_improvement": mean(diffs), "lower95": bootstrap_lower(diffs), "pairs": len(diffs)}


def markdown(title: str, rows: list[dict]) -> str:
    head = ("| Opponent | Fights | W/D/L | Score | 95% LB | Draw | Round 2 | R0 KO | Trailer wins | Exhausted |\n"
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    body = [f"| {r['opponent']} | {r['fights']} | {r['W']}/{r['D']}/{r['L']} | {r['score']:.3f} | "
            f"{r['lower95']:.3f} | {r['draw_rate']:.1%} | {r['round2_rate']:.1%} | {r['round0_ko_rate']:.1%} | "
            f"{r['trailing_after_r0_win_rate']:.1%} | {r['exhausted_rate']:.1%} |" for r in rows]
    return f"### {title}\n\n{head}\n" + "\n".join(body) + "\n"
