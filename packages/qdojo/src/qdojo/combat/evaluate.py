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
from dataclasses import dataclass, field, replace
from typing import Callable

from ..hashing import sha256
from . import npcs
from .engine import resolve_beat, resolve_round
from .rules import Ruleset, candidate_1
from .training import Contestant, run_fight
from .types import ATTACKS, NO_POWER, SUBMITTED, Action, FightState, Plan, submitted

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


def _sample_plans(rng: random.Random, n: int, acts=SUBMITTED):
    return [tuple(rng.choice(acts) for _ in range(6)) for _ in range(n)]


def _round_value(rules, me, opp, mine: Plan, theirs: Plan, round_index: int = 0) -> int:
    """HP margin gained over one round, plus a small stamina term; KO dominates."""
    start = FightState(round_index, me, opp)
    res = resolve_round(rules, start, mine, theirs)
    a, b = res.beats[-1].a.after, res.beats[-1].b.after
    if b.hp == 0 and a.hp > 0:
        return 10_000
    if a.hp == 0 and b.hp > 0:
        return -10_000
    v = 8 * ((a.hp - me.hp) - (b.hp - opp.hp)) + (a.stamina - b.stamina)
    if rules.last_stand is not None:                    # candidate 3: value an opening carried out of the round
        v += 4 * rules.opening_damage * ((a.opening > 0) - (b.opening > 0))
    return v


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
        pool = _sample_plans(rng, self.candidates, submitted(rules)) + [
            (J, J, J, R, J, J), (D, K, R, D, K, R), (B, T, R, D, J, R), (T, J, D, K, R, J)]
        for acts in pool:
            slot = NO_POWER
            if power_ok:
                slot = next((i for i, a in enumerate(acts) if a in ATTACKS), NO_POWER)
            plan = Plan.of(acts, slot)
            v = sum(_round_value(rules, me, opp, plan, o, obs.round_index) for o in opp_plans)
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


def _beat_value(a, b, rules=None) -> int:
    if b.hp == 0 and a.hp > 0:
        return 10**6
    if a.hp == 0 and b.hp > 0:
        return -10**6
    v = 8 * (a.hp - b.hp) + (a.stamina - b.stamina)
    if rules is not None and rules.last_stand is not None:     # candidate 3: an opening held is worth half its bonus
        v += 4 * rules.opening_damage * ((a.opening > 0) - (b.opening > 0))
    return v


def beam_response(rules: Ruleset, me, opp, opp_plans: list[Plan], beam: int = 48, round_index: int = 0) -> Plan:
    """Best-scoring six-action plan against predicted opponent plans, by beam
    search over beats (exact resolution, summed over the predictions). A beam
    that reaches a knockout stops expanding: later actions are never executed."""
    key = (rules.digest, me, opp, tuple(opp_plans), beam, round_index)
    hit = _BEAM_CACHE.get(key)
    if hit is not None:
        return hit
    plan = _beam(rules, me, opp, opp_plans, beam, round_index)
    if len(_BEAM_CACHE) > 20_000:          # bounded: the campaign runs on a small host
        _BEAM_CACHE.clear()
    _BEAM_CACHE[key] = plan
    return plan


_BEAM_CACHE: dict = {}


def _beam(rules, me, opp, opp_plans, beam, round_index=0):
    power_ok = bool(me.power_available)
    # Beam entries: (value, actions, power_slot, per-prediction (me, opp) states, finished flags)
    entries = [(0, (), NO_POWER, tuple((me, opp) for _ in opp_plans), tuple(False for _ in opp_plans))]
    for i in range(6):
        grown = []
        for _, acts, slot, states, done in entries:
            for a in submitted(rules):
                options = [False]
                if power_ok and slot == NO_POWER and a in ATTACKS:
                    options.append(True)
                for pw in options:
                    total, nxt, fin = 0, [], []
                    for k, ((sa, sb), d) in enumerate(zip(states, done)):
                        if d:
                            nxt.append((sa, sb))
                            fin.append(True)
                            total += _beat_value(sa, sb, rules)
                            continue
                        ob = opp_plans[k]
                        na, nb, _ = resolve_beat(rules, sa, sb, a, ob.actions[i], pw, ob.power_slot == i,
                                                 round_index=round_index)
                        ko = na.hp == 0 or nb.hp == 0
                        nxt.append((na, nb))
                        fin.append(ko)
                        total += _beat_value(na, nb, rules)
                    grown.append((total, acts + (a,), i if pw else slot, tuple(nxt), tuple(fin)))
        grown.sort(key=lambda e: -e[0])
        entries = grown[:beam]
    best = entries[0]
    return Plan.of(best[1], best[2])


def _opp_observation(obs):
    other = "B" if obs.slot == "A" else "A"
    mine = tuple(tuple((b.a if obs.slot == "A" else b.b).effective for b in r.beats) for r in obs.prior)
    return npcs.Observation(obs.round_index, obs.opponent_state, obs.self_state, mine, other, obs.prior)


@dataclass
class KnownPolicyResponse:
    """Counter instrument: the opponent's policy is known (a published script,
    or a style scouted from history); predict its plans and best-respond."""
    opponent: npcs.Policy
    samples: int = 3
    beam: int = 48

    def __call__(self, rules, obs, stream):
        view = _opp_observation(obs)
        preds = []
        for k in range(self.samples):
            s = npcs.Stream(sha256(TAG_EVAL, b"known", bytes([k])), obs.round_index, obs.round_index)
            preds.append(self.opponent(rules, view, s))
        return beam_response(rules, obs.self_state, obs.opponent_state, preds, self.beam, obs.round_index)


@dataclass
class ReaderPlanner:
    """A strategy family: assume the opponent repeats its last revealed plan
    (weighted), hedge with generic mixed plans, and best-respond by beam search.
    Round 0 has no history and plays mixed-v1. Ablations: `use_history=False`
    predicts from generic plans only; `ignore_resources` plans as if both
    fighters were at the initial state."""
    use_history: bool = True
    ignore_resources: bool = False
    repeat_weight: int = 2
    hedges: int = 2
    beam: int = 32
    name: str = "reader-v1"

    def __call__(self, rules, obs, stream):
        if not obs.prior and self.use_history:
            return npcs.mixed_v1(rules, obs, stream)
        me, opp = obs.self_state, obs.opponent_state
        preds = []
        if self.use_history and obs.prior:
            last = obs.prior[-1]
            p = last.plan_b if obs.slot == "A" else last.plan_a
            preds += [Plan.of(p.actions)] * self.repeat_weight
        generic = npcs.Observation(obs.round_index, opp, me)
        for _ in range(self.hedges if self.use_history else self.hedges + self.repeat_weight):
            preds.append(Plan.of(npcs.mixed_v1(rules, generic, stream).actions))
        if self.ignore_resources:
            init = npcs.FighterState.initial(rules)
            plan = beam_response(rules, replace(init, power_available=me.power_available), init, preds, self.beam,
                                 obs.round_index)
            if plan.power_slot != NO_POWER and not me.power_available:
                plan = Plan.of(plan.actions)
            return plan
        return beam_response(rules, me, opp, preds, self.beam, obs.round_index)


_SCRIPTS: dict[tuple[bytes, str], Plan] = {}


def strong_script(rules: Ruleset, versus: str) -> npcs.Policy:
    """A predictable but competent opponent: one fixed plan, chosen by beam
    search as the best reply to eight round-0 plans of `versus`, replayed
    every round (power on its first attack in the last round)."""
    key = (rules.digest, versus)
    if key not in _SCRIPTS:
        s0 = npcs.FighterState.initial(rules)
        obs = npcs.Observation(0, s0, s0)
        pol = npcs.ROSTER[versus].policy
        preds = [Plan.of(pol(rules, obs, npcs.Stream(sha256(TAG_EVAL, b"script", versus.encode(), bytes([i])), 0, 0))
                         .actions) for i in range(8)]
        _SCRIPTS[key] = beam_response(rules, s0, s0, preds)
    return pattern(_SCRIPTS[key].actions)


def exploit_opening(opening: Plan, then: npcs.Policy = npcs.mixed_v1):
    def policy(rules, obs, rng):
        return opening if obs.round_index == 0 else then(rules, obs, rng)
    return policy


def pools(rules: Ruleset | None = None) -> dict[str, dict[str, npcs.Policy]]:
    """Named opponent pools. 'baseline' is the model.md §2 exploit list. The
    scripted opponents are best replies computed under `rules` (default
    candidate 1), so each ruleset gets its own competent scripts."""
    rules = rules or candidate_1()
    roster = {n.id: n.policy for n in npcs.ROSTER.values()}
    spams = {f"spam-{a.name.lower()}": spam(a) for a in SUBMITTED}
    spams["spam-jab-spend-power"] = spam(J, 0)
    cycles = {f"cycle-{x.name.lower()}-{y.name.lower()}": pattern([x, y] * 3)
              for x, y in itertools.combinations(SUBMITTED, 2)}
    if len(rules.submitted) > 6:                      # candidate 3: spam and cycles with the new actions too
        for new in (Action.LAST_STAND, Action.FEINT):
            tag = new.name.lower().replace("_", "-")
            spams[f"spam-{tag}"] = spam(new)
            cycles.update({f"cycle-{x.name.lower()}-{tag}": pattern([x, new] * 3) for x in SUBMITTED})
        cycles["cycle-feint-last-stand"] = pattern([Action.FEINT, Action.LAST_STAND] * 3)
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
    scripts = {f"script-vs-{v}": strong_script(rules, v) for v in ("mixed-v1", "random-v1", "scout-v1", "kicker-v1")}
    if len(rules.submitted) > 6:                      # a scripted user of each new action
        held_out_styles["stander"] = pattern([J, Action.LAST_STAND, R, J, Action.LAST_STAND, B])
        held_out_styles["feinter"] = pattern([Action.FEINT, K, J, Action.FEINT, Action.LAST_STAND, R])
    fixed_style = {k: roster[k] for k in ("jabber-v1", "turtle-v1", "kicker-v1")} | held_out_styles
    # The in-process policies the public demo arena's house bots run (its
    # lineup also has LLM bots, which no local benchmark can reproduce).
    house = {k: roster[k] for k in ("scout-v1", "mixed-v1", "kicker-v1", "jabber-v1")}
    house.update({"reader-v1": ReaderPlanner(), "search-v1": SearchPlanner(),
                  "script-vs-scout-v1": scripts["script-vs-scout-v1"],
                  "script-vs-mixed-v1": scripts["script-vs-mixed-v1"], "repeat-last-winner": repeat_last_winner})
    # A builder's default benchmark: every NPC, the house policies, and under
    # candidate 3 a scripted user of each new move.
    builder = {**roster, **house}
    if len(rules.submitted) > 6:
        builder.update({k: held_out_styles[k] for k in ("stander", "feinter")})
    return {
        "roster": roster,
        "house": house,
        "builder": builder,
        "baseline": {**roster, **spams, **cycles, **misc},
        "fixed-style": fixed_style,
        # Predictable but competent: fixed plans that beat the roster's generic play.
        "scripts": scripts,
        "predictable": fixed_style | scripts,
        "competent": {"mixed-v1": roster["mixed-v1"], "scout-v1": roster["scout-v1"],
                      "search-v1": SearchPlanner(), "reader-v1": ReaderPlanner(),
                      "repeat-last-winner": repeat_last_winner},
    }


def policy_by_name(name: str, rules: Ruleset | None = None) -> npcs.Policy:
    if name in npcs.ROSTER:
        return npcs.ROSTER[name].policy
    if name == "search-v1":
        return SearchPlanner()
    if name == "search-blind":
        return SearchPlanner(use_history=False, name="search-blind")
    if name == "search-nores":
        return SearchPlanner(ignore_resources=True, name="search-nores")
    if name == "reader-v1":
        return ReaderPlanner()
    if name == "reader-blind":
        return ReaderPlanner(use_history=False, name="reader-blind")
    if name == "reader-nores":
        return ReaderPlanner(ignore_resources=True, name="reader-nores")
    for pool in pools(rules).values():
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
    kos: int = 0                   # fights ended by KO or double KO
    decisions: int = 0             # fights decided on HP after the last round (ties included)
    opening_bonus_hp: int = 0      # this side's opening bonus damage
    power_bonus_hp: int = 0        # this side's power bonus damage
    leader_after_r1: int = 0       # fights reaching the last round with an HP leader after the second
    leader_after_r1_won: int = 0
    action_beats: dict = field(default_factory=dict)   # effective action -> [beats, dealt, taken], this side


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
    t.kos += out["result"] in ("KO", "DOUBLE_KO")
    t.decisions += out["result"] in ("HP", "HP_TIE")
    if len(rounds) >= 3:
        ea, eb = rounds[1]["end"]["A"]["hp"], rounds[1]["end"]["B"]["hp"]
        if ea != eb:
            t.leader_after_r1 += 1
            t.leader_after_r1_won += out["winner"] == ("A" if ea > eb else "B")
    for r in rounds:
        for beat in r["beats"]:
            me, them = beat[slot], beat[other]
            t.opening_bonus_hp += me["opening_bonus"]
            t.power_bonus_hp += me["power_bonus"]
            row = t.action_beats.setdefault(me["effective"], [0, 0, 0])
            row[0] += 1
            row[1] += me["computed_damage"]
            row[2] += them["computed_damage"]
    return score


def eval_seed(suite: str, n: int) -> bytes:
    """The fight seed of paired trial `n` in a seed suite (the same for every policy and planner)."""
    return sha256(TAG_EVAL, suite.encode(), n.to_bytes(8, "little"))


@dataclass
class PlannerRecord:
    """How an external planner command behaved over an evaluation. A round it
    failed (timeout, crash, invalid output) was played with the fallback plan:
    that fight's result is not the planner's play, and it is counted here."""
    rounds: int = 0
    fallback_rounds: int = 0
    fights: int = 0
    fights_with_fallback: int = 0
    adjusted_rounds: int = 0
    failures: dict = field(default_factory=dict)     # PlannerError code -> rounds
    max_ms: int = 0
    total_ms: int = 0
    first_error: str | None = None

    def add(self, diagnostics: list[dict]):
        self.fights += 1
        failed = False
        for d in diagnostics:
            self.rounds += 1
            if d.get("error"):
                failed = True
                self.fallback_rounds += 1
                self.failures[d["error"]] = self.failures.get(d["error"], 0) + 1
                if self.first_error is None:
                    tail = (d.get("stderr") or "").strip().splitlines()
                    self.first_error = d["error"] + (": " + tail[-1][:300] if tail else "")
            else:
                self.max_ms = max(self.max_ms, d.get("elapsed_ms", 0))
                self.total_ms += d.get("elapsed_ms", 0)
            self.adjusted_rounds += bool(d.get("adjusted"))
        self.fights_with_fallback += failed

    def to_json(self) -> dict:
        ok = self.rounds - self.fallback_rounds
        return {"rounds": self.rounds, "fallback_rounds": self.fallback_rounds, "fights": self.fights,
                "fights_with_fallback": self.fights_with_fallback, "adjusted_rounds": self.adjusted_rounds,
                "failures": dict(sorted(self.failures.items())), "max_ms": self.max_ms,
                "mean_ms": round(self.total_ms / ok, 1) if ok else None, "first_error": self.first_error}


def paired(x: npcs.Policy | None, y: npcs.Policy, seeds: int, suite: str, x_id="x", y_id="y",
           rules: Ruleset | None = None, first_seed: int = 0, x_command: list[str] | None = None,
           budget_ms: int | None = None, record: PlannerRecord | None = None) -> Tally:
    """`seeds` paired trials; each plays twice with fighter slots swapped.
    With `x_command` the evaluated side is that planner process (run exactly as
    `qdojo combat train` runs it, same limits and fallback), and its
    diagnostics go into `record`."""
    rules = rules or candidate_1()
    t = Tally()
    for n in range(first_seed, first_seed + seeds):
        seed = eval_seed(suite, n)
        pair_score = 0.0
        for names in (("P", "Q"), ("Q", "P")):
            if x_command is not None:
                cx = Contestant(names[0], command=list(x_command),
                                **({"budget_ms": budget_ms} if budget_ms is not None else {}))
            else:
                cx = Contestant(names[0], policy=x, policy_id=x_id)
            cy = Contestant(names[1], policy=y, policy_id=y_id)
            replay = run_fight(cx, cy, seed, n + 1, rules)
            slot = "A" if replay["fighters"]["A"]["name"] == names[0] else "B"
            pair_score += _record(t, replay, slot)
            if record is not None and x_command is not None:
                record.add(cx.diagnostics)
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
        "ko_rate": t.kos / t.fights, "decision_rate": t.decisions / t.fights,
        "beats_per_fight": t.executed_beats / t.fights,
        "opening_bonus_per_fight": t.opening_bonus_hp / t.fights, "power_bonus_per_fight": t.power_bonus_hp / t.fights,
        "leader_after_r1_win_rate": t.leader_after_r1_won / t.leader_after_r1 if t.leader_after_r1 else float("nan"),
    }


def evaluate(policy: npcs.Policy, pool: dict[str, npcs.Policy], seeds: int, suite: str = "test",
             policy_id: str = "policy", progress: Callable[[str], None] | None = None,
             rules: Ruleset | None = None) -> list[dict]:
    rows = []
    for name, opp in pool.items():
        t = paired(policy, opp, seeds, f"{suite}/{name}", policy_id, name, rules=rules)
        rows.append(summarize(name, t))
        if progress:
            progress(f"{name}: score {rows[-1]['score']:.3f}")
    return rows


def evaluate_planner(command: list[str], pool: dict[str, npcs.Policy], seeds: int, suite: str = "test",
                     rules: Ruleset | None = None, budget_ms: int | None = None,
                     progress: Callable[[str], None] | None = None) -> dict:
    """A planner command against every opponent in `pool` on the evaluation
    seeds of `suite`: per-opponent rows, the per-seed pair scores (for paired
    comparisons) and the planner's failure record."""
    rows, scores, record = [], {}, PlannerRecord()
    for name, opp in pool.items():
        before = record.fallback_rounds
        t = paired(None, opp, seeds, f"{suite}/{name}", "planner", name, rules=rules, x_command=command,
                   budget_ms=budget_ms, record=record)
        row = summarize(name, t)
        row["fallback_rounds"] = record.fallback_rounds - before
        rows.append(row)
        scores[name] = t.scores
        if progress:
            progress(f"{name}: score {row['score']:.3f} ({row['W']}/{row['D']}/{row['L']})"
                     + (f", {row['fallback_rounds']} fallback rounds" if row["fallback_rounds"] else ""))
    every = [x for name in pool for x in scores[name]]
    total = {"opponent": "ALL", "fights": sum(r["fights"] for r in rows), "W": sum(r["W"] for r in rows),
             "D": sum(r["D"] for r in rows), "L": sum(r["L"] for r in rows), "score": mean(every),
             "lower95": bootstrap_lower(every), "fallback_rounds": record.fallback_rounds}
    return {"command": command, "rows": rows, "total": total, "planner": record.to_json(), "pair_scores": scores}


def compare(base: dict, other: dict) -> dict:
    """Paired difference other-minus-base over identical seeds and opponents."""
    diffs = [y - x for name in base["pair_scores"] for x, y in zip(base["pair_scores"][name], other["pair_scores"][name])]
    return {"base": base["command"], "other": other["command"], "pairs": len(diffs),
            "mean_difference": mean(diffs), "lower95": bootstrap_lower(diffs),
            "upper95": -bootstrap_lower([-d for d in diffs])}


def planner_markdown(title: str, result: dict) -> str:
    head = ("| Opponent | Fights | W/D/L | Score | 95% LB | Fallback rounds |\n"
            "|---|---:|---|---:|---:|---:|")
    fmt = lambda r: (f"| {r['opponent']} | {r['fights']} | {r['W']}/{r['D']}/{r['L']} | {r['score']:.3f} | "  # noqa: E731
                     f"{r['lower95']:.3f} | {r['fallback_rounds']} |")
    body = [fmt(r) for r in result["rows"]] + [fmt({**result["total"], "opponent": "**ALL**"})]
    return f"### {title}\n\n{head}\n" + "\n".join(body) + "\n"


def ablation(full: npcs.Policy, ablated: npcs.Policy, pool: dict[str, npcs.Policy], seeds: int,
             suite: str = "ablation", rules: Ruleset | None = None) -> dict:
    """Paired difference full-minus-ablated on identical seeds and opponents."""
    diffs = []
    for name, opp in pool.items():
        a = paired(full, opp, seeds, f"{suite}/{name}", rules=rules)
        b = paired(ablated, opp, seeds, f"{suite}/{name}", rules=rules)
        diffs += [x - y for x, y in zip(a.scores, b.scores)]
    return {"mean_improvement": mean(diffs), "lower95": bootstrap_lower(diffs), "pairs": len(diffs)}


def markdown(title: str, rows: list[dict]) -> str:
    head = ("| Opponent | Fights | W/D/L | Score | 95% LB | Draw | Round 2 | R0 KO | Trailer wins | Exhausted |\n"
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    body = [f"| {r['opponent']} | {r['fights']} | {r['W']}/{r['D']}/{r['L']} | {r['score']:.3f} | "
            f"{r['lower95']:.3f} | {r['draw_rate']:.1%} | {r['round2_rate']:.1%} | {r['round0_ko_rate']:.1%} | "
            f"{r['trailing_after_r0_win_rate']:.1%} | {r['exhausted_rate']:.1%} |" for r in rows]
    return f"### {title}\n\n{head}\n" + "\n".join(body) + "\n"
