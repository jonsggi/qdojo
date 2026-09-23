"""Free local practice: no wallet, NFT, node or signing (docs/npcs.md §1).

A fight here runs the same engine a ranked fight does. Each side is either a
disclosed NPC or the owner's planner process. The result is a replay that
`verify_replay` re-derives from its plans alone, without trusting any stored
state or outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..hashing import sha256
from . import codec, npcs, planner
from .engine import new_fight, resolve_beat, resolve_round
from .rules import Ruleset, candidate_1
from .types import SUBMITTED, Action, FighterState, FightState, Plan, Reason, RoundResult

REPLAY_SCHEMA = "qdojo.combat.replay.v1"
TAG_PRACTICE_FIGHTER = b"qdojo/combat/practice-fighter/v1\0"
TAG_PRACTICE_SIDE = b"qdojo/combat/practice-side/v1\0"
ZERO32 = bytes(32)


def practice_fighter_id(name: str) -> bytes:
    return sha256(TAG_PRACTICE_FIGHTER, name.encode("utf-8"))


@dataclass
class Contestant:
    """A rostered NPC id, an in-process policy, or a planner command.
    `name` must be unique within a fight; it derives the practice fighter ID."""
    name: str
    npc: str | None = None
    command: list[str] | None = None
    policy: npcs.Policy | None = None
    policy_id: str | None = None
    budget_ms: int = planner.DEFAULT_BUDGET_MS
    fallback: Plan = planner.FALLBACK
    diagnostics: list = field(default_factory=list)

    def __post_init__(self):
        if sum(x is not None for x in (self.npc, self.command, self.policy)) != 1:
            raise ValueError("a contestant is exactly one of: NPC, policy, planner command")
        if self.npc is not None:
            if self.npc not in npcs.ROSTER:
                raise KeyError(f"unknown NPC {self.npc!r}; known: {', '.join(npcs.ROSTER)}")
            self.policy, self.policy_id = npcs.ROSTER[self.npc].policy, self.npc

    @property
    def label(self) -> dict:
        if self.npc:
            return {"name": self.name, "kind": "npc", "policy": self.npc}
        if self.policy:
            return {"name": self.name, "kind": "policy", "policy": self.policy_id or "unnamed"}
        return {"name": self.name, "kind": "planner"}


def practice_context(rules: Ruleset, fight_number: int, ids: tuple[bytes, bytes]) -> codec.FightContext:
    """A zero-stake exhibition context on the all-zero network: gives local
    practice real round-state digests without pretending to be a deployment."""
    def part(fid):
        return codec.Participant(fid, ZERO32, ZERO32, 0, ZERO32, 1000, 1000)
    return codec.FightContext(
        network_id=ZERO32, contract_id=ZERO32, contest_id=fight_number, fight_id=fight_number,
        mode=codec.Mode.EXHIBITION, series_format=codec.Format.SINGLE, cup_id=0, season_id=0,
        start_tick=0, ruleset_digest=rules.digest, commit_ticks=0, reveal_ticks=0,
        fee_profile_id=0, stake_per_fighter=0, rake_bps=0, house_bps=0, dev_bps=0, share_bps=0,
        house_recipient=ZERO32, dev_recipient=ZERO32, share_recipient=ZERO32,
        participant_a=part(ids[0]), participant_b=part(ids[1]))


def _executed_actions(result: RoundResult, slot: str) -> tuple[Action, ...]:
    return tuple((b.a if slot == "A" else b.b).effective for b in result.beats)


def _fighter_json(fid: bytes, s: FighterState) -> dict:
    return {"fighter_id": fid.hex(), "hp": s.hp, "stamina": s.stamina, "opening": s.opening,
            "guard_streak": s.guard_streak, "power_available": bool(s.power_available)}


def observation(rules, ctx, state: FightState, slot: str, ids, prior: list[dict], budget_ms: int) -> dict:
    """docs/api.md §1, for local practice: no deadlines exist, so none are invented."""
    me, opp = (state.a, state.b) if slot == "A" else (state.b, state.a)
    my_id, opp_id = (ids[0], ids[1]) if slot == "A" else (ids[1], ids[0])
    return {
        "schema": planner.OBSERVATION_SCHEMA,
        "mode": "practice",
        "network_id": ctx.network_id.hex(), "contract_id": ctx.contract_id.hex(),
        "fight_id": str(ctx.fight_id), "contest_id": str(ctx.contest_id),
        "round_index": state.round_index, "self_slot": slot,
        "ruleset_digest": rules.digest.hex(), "context_digest": ctx.digest().hex(),
        "round_state_digest": codec.round_state_digest(ctx.digest(), state.round_index, state.a, state.b).hex(),
        "self": _fighter_json(my_id, me), "opponent": _fighter_json(opp_id, opp),
        "deadlines": None, "observed_tick": None,
        "prior_rounds": prior,
        "history_manifest": {"opponent_fight_ids": [], "as_of_tick": None},
        "decision_budget_ms": budget_ms,
    }


def run_fight(a: Contestant, b: Contestant, seed: bytes, fight_number: int = 1,
              rules: Ruleset | None = None) -> dict:
    """Play one fight. Slot A is the smaller practice fighter ID, as in ranked play."""
    rules = rules or candidate_1()
    if len(seed) != 32:
        raise ValueError("a practice seed is 32 bytes")
    if a.name == b.name:
        raise ValueError("contestants need distinct names")
    pair = sorted([(practice_fighter_id(a.name), a), (practice_fighter_id(b.name), b)], key=lambda p: p[0])
    ids = (pair[0][0], pair[1][0])
    sides = {"A": pair[0][1], "B": pair[1][1]}
    ctx = practice_context(rules, fight_number, ids)
    side_seed = {s: sha256(TAG_PRACTICE_SIDE, seed, s.encode()) for s in "AB"}
    state = new_fight(rules)
    rounds, prior, history, results = [], [], {"A": [], "B": []}, []
    fallbacks = []
    while state.outcome is None:
        plans = {}
        for slot, who in sides.items():
            other = "B" if slot == "A" else "A"
            if who.policy:
                me, opp = (state.a, state.b) if slot == "A" else (state.b, state.a)
                obs = npcs.Observation(state.round_index, me, opp, tuple(history[other]), slot, tuple(results))
                rng = npcs.Stream(side_seed[slot], fight_number, state.round_index)
                plans[slot] = who.policy(rules, obs, rng)
            else:
                obs = observation(rules, ctx, state, slot, ids, prior, who.budget_ms)
                ran, err = planner.run_or_fallback(who.command, obs, who.budget_ms, who.fallback)
                plans[slot] = ran.plan
                who.diagnostics.append({"round_index": state.round_index, "elapsed_ms": ran.elapsed_ms,
                                        "stderr": ran.stderr[-2000:], "error": err.code if err else None})
                if err:
                    fallbacks.append({"slot": slot, "round_index": state.round_index,
                                      "code": "FALLBACK_PLAN_USED", "cause": err.code})
        res = resolve_round(rules, state, plans["A"], plans["B"])
        results.append(res)
        for slot in "AB":
            history[slot].append(_executed_actions(res, slot))
        entry = res.to_json()
        entry["round_state_digest"] = codec.round_state_digest(ctx.digest(), state.round_index, state.a, state.b).hex()
        entry["unexecuted"] = {s: [x.name for x in p.actions[res.executed:]]
                               for s, p in (("A", res.plan_a), ("B", res.plan_b))}
        rounds.append(entry)
        prior.append(entry)
        state = res.end
    return {
        "schema": REPLAY_SCHEMA, "mode": "practice",
        "ruleset_digest": rules.digest.hex(), "semantic_version": rules.semantic_version,
        "seed": seed.hex(), "fight_number": fight_number,
        "context_digest": ctx.digest().hex(),
        "fighters": {"A": {**sides["A"].label, "fighter_id": ids[0].hex()},
                     "B": {**sides["B"].label, "fighter_id": ids[1].hex()}},
        "rounds": rounds,
        "outcome": state.outcome.to_json(),
        "final": {"A": state.a.to_json(), "B": state.b.to_json()},
        "fallbacks": fallbacks,
    }


class ReplayMismatch(ValueError):
    pass


def verify_replay(replay: dict, rules: Ruleset | None = None) -> dict:
    """Re-derive every round from the recorded plans; compare everything else.

    Only the plans (and the ruleset digest) are inputs. States, traces and the
    outcome in the file are claims, checked against an independent resolution.
    """
    rules = rules or candidate_1()
    if replay.get("schema") != REPLAY_SCHEMA:
        raise ReplayMismatch(f"not a {REPLAY_SCHEMA} document")
    if replay.get("ruleset_digest") != rules.digest.hex():
        raise ReplayMismatch("replay names a different ruleset")
    state = new_fight(rules)
    for i, entry in enumerate(replay["rounds"]):
        if state.outcome is not None:
            raise ReplayMismatch(f"round {i} recorded after the fight ended")
        plans = entry["plans"]
        res = resolve_round(rules, state, Plan.of(plans["A"]["actions"], plans["A"]["power_slot"]),
                            Plan.of(plans["B"]["actions"], plans["B"]["power_slot"]))
        recomputed = res.to_json()
        for key in ("start", "executed_beats", "beats", "break_recovery", "end"):
            if recomputed[key] != entry.get(key):
                raise ReplayMismatch(f"round {i}: recorded {key} differs from the re-derived one")
        state = res.end
    if state.outcome is None:
        raise ReplayMismatch("replay stops before the fight ended")
    if state.outcome.to_json() != replay.get("outcome"):
        raise ReplayMismatch("recorded outcome differs from the re-derived one")
    return state.outcome.to_json()


# ---- explanations ----------------------------------------------------------

def _score(rules, me, opp, mine, theirs):
    """Hindsight value of one beat: 4*(dealt - taken) + own stamina change."""
    m2, _, tr = resolve_beat(rules, me, opp, mine, theirs)
    return 4 * (tr.a.computed_damage - tr.b.computed_damage) + m2.stamina - me.stamina, tr


def explain(replay: dict, slot: str, rules: Ruleset | None = None) -> list[str]:
    """Plain sentences for the beats that cost `slot` something (combat.md §9).
    Alternatives are labelled hindsight: they hold the opponent's recorded
    action fixed, which is not proof the opponent would have played it."""
    rules = rules or candidate_1()
    other = "B" if slot == "A" else "A"
    lines = []
    for r in replay["rounds"]:
        ri = r["round_index"]
        for beat in r["beats"]:
            me, them = beat[slot], beat[other]
            where = f"Round {ri + 1}, beat {beat['beat'] + 1}"
            reasons = set(me["reasons"])
            parts = []
            if "INSUFFICIENT_STAMINA" in reasons:
                parts.append(f"your {me['intended']} cost {me['cost']}; you had {me['before']['stamina']}, "
                             f"so you were exposed")
            if me["actual_hp_lost"]:
                how = f"took {me['actual_hp_lost']} from their {them['effective']}"
                if them["bonus_damage"]:
                    how += f" ({them['base_damage']} base + {them['bonus_damage']} opening/power)"
                parts.append(how)
            if "RECOVERY_PUNISHED" in reasons:
                parts.append("your recovery was hit, so it restored only "
                             f"{rules.recover_hit} instead of {rules.recover_unhit}")
            if "GUARD_STRAIN" in reasons and me["strain"]:
                parts.append(f"their kick drained {me['strain']} extra stamina through your block")
            if "POWER_WASTED" in reasons:
                parts.append("your power strike was spent without landing")
            if "BLOCKED" in reasons or "EVADED" in reasons or "THROW_INTERRUPTED" in reasons:
                parts.append(f"your {me['effective']} did nothing against their {them['effective']}")
            if not parts:
                continue
            before = FighterState(**me["before"])
            opp_before = FighterState(**them["before"])
            theirs = Action[them["effective"]] if them["effective"] != "EXHAUSTED" else None
            hint = ""
            if theirs is not None:
                best =max(SUBMITTED, key=lambda x: (_score(rules, before, opp_before, x, theirs)[0], -int(x)))
                if best.name != me["intended"]:
                    _, tr = _score(rules, before, opp_before, best, theirs)
                    hint = (f" Hindsight, against their recorded {theirs.name}: {best.name} would have dealt "
                            f"{tr.a.computed_damage} and taken {tr.b.computed_damage}.")
            lines.append(f"{where}: " + "; ".join(parts) + "." + hint)
    return lines


def summary(replay: dict, slot: str) -> dict:
    """Per-fight training numbers for one side (docs/npcs.md §4)."""
    other = "B" if slot == "A" else "A"
    counts = {"exhausted_beats": 0, "wasted_power": 0, "recovery_punished": 0,
              "guard_broken": 0, "opening_converted": 0, "executed_beats": 0}
    for r in replay["rounds"]:
        for beat in r["beats"]:
            me, them = beat[slot], beat[other]
            reasons = set(me["reasons"])
            counts["executed_beats"] += 1
            counts["exhausted_beats"] += "INSUFFICIENT_STAMINA" in reasons
            counts["wasted_power"] += "POWER_WASTED" in reasons
            counts["recovery_punished"] += "RECOVERY_PUNISHED" in reasons
            counts["guard_broken"] += me["effective"] == "BLOCK" and them["effective"] == "THROW"
            counts["opening_converted"] += "OPENING_USED" in reasons
    out = replay["outcome"]
    score = 0.5 if out["winner"] is None else 1.0 if out["winner"] == slot else 0.0
    final = replay["final"]
    return {"score": score, "result": out["result"], "rounds": len(replay["rounds"]),
            "hp_margin": final[slot]["hp"] - final[other]["hp"], **counts}


def reason_codes() -> list[str]:
    return [r.value for r in Reason]
