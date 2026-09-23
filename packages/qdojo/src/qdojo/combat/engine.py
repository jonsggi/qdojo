"""Pure combat resolution: beat, round, fight. No I/O, clock, RNG or floats.

Each step of resolve_beat is numbered as in docs/combat.md §6 and reads only
the two pre-beat snapshots; neither fighter is updated before both halves of
the beat have been computed. Resolution is side-symmetric: swapping A and B
swaps the trace and the result, and nothing else.
"""
from __future__ import annotations

from dataclasses import replace

from .rules import Ruleset, candidate_1
from .types import (
    ATTACKS, NO_POWER, Action, BeatTrace, FighterState, FightState, Outcome, Plan,
    PlanError, Reason, Result, RoundResult, SideTrace, StateError,
)


def new_fight(rules: Ruleset | None = None) -> FightState:
    rules = rules or candidate_1()
    s = FighterState.initial(rules)
    return FightState(0, s, s)


def action_cost(rules: Ruleset, state: FighterState, action: Action, power: bool) -> int:
    cost = rules.base_costs[action]
    if action is Action.BLOCK:
        cost += rules.block_streak_cost * state.guard_streak
    if power:
        cost += rules.power_cost
    return cost


def validate_plan(rules: Ruleset, state: FighterState, plan: Plan) -> None:
    """The whole plan, before any combat, including beats a knockout may skip."""
    if not isinstance(plan, Plan) or len(plan.actions) != rules.beats_per_round:
        raise PlanError("a plan has exactly six actions")
    for a in plan.actions:
        if not isinstance(a, Action) or a is Action.EXHAUSTED:
            raise PlanError(f"illegal submitted action {a!r}")
    if plan.power_slot != NO_POWER:
        if type(plan.power_slot) is not int or not 0 <= plan.power_slot < rules.beats_per_round:
            raise PlanError(f"invalid power_slot {plan.power_slot!r}")
        if plan.actions[plan.power_slot] not in ATTACKS:
            raise PlanError("power_slot must select JAB, KICK or THROW")
        if not state.power_available:
            raise PlanError("power strike already spent this fight")


def _prepare(rules, s: FighterState, intended: Action, power: bool):
    """Steps 1-3 for one fighter: cost, power spend, effective action."""
    cost = action_cost(rules, s, intended, power)                  # 1
    power_available = 0 if power else s.power_available            # 2
    if s.stamina >= cost:                                          # 3
        return intended, cost, cost, s.stamina - cost, power_available
    return Action.EXHAUSTED, cost, 0, s.stamina, power_available


def _reasons(rules, s, nxt, intended, own, opp, power, base, dealt, incoming, strain):
    """Explanatory codes only; nothing reads these to decide an outcome."""
    r = []
    if own is Action.EXHAUSTED:
        r.append(Reason.INSUFFICIENT_STAMINA)
    if dealt > 0:
        r.append(Reason.HIT)
    elif own in ATTACKS:
        if own is Action.THROW and opp is Action.THROW:
            r.append(Reason.THROW_CLASH)
        elif own is Action.THROW and opp in (Action.JAB, Action.KICK):
            r.append(Reason.THROW_INTERRUPTED)
        elif opp is Action.BLOCK:
            r.append(Reason.BLOCKED)
        elif opp is Action.DUCK:
            r.append(Reason.EVADED)
    if own is Action.RECOVER and incoming > 0:
        r.append(Reason.RECOVERY_PUNISHED)
    if own is Action.BLOCK and opp is Action.KICK:
        r.append(Reason.GUARD_STRAIN)
    if s.opening:
        r.append(Reason.OPENING_USED if base > 0 else Reason.OPENING_EXPIRED)
    if power:
        r.append(Reason.POWER_USED if base > 0 and own is intended else Reason.POWER_WASTED)
    if nxt.opening:
        r.append(Reason.OPENING_EARNED)
    return r


def resolve_beat(rules: Ruleset, a: FighterState, b: FighterState,
                 intent_a: Action, intent_b: Action,
                 power_a: bool = False, power_b: bool = False, index: int = 0):
    """One simultaneous beat from two snapshots. Returns (a', b', BeatTrace)."""
    snaps = (a, b)
    intents = (Action(intent_a), Action(intent_b))
    powers = (bool(power_a), bool(power_b))
    for s, act, pw in zip(snaps, intents, powers):
        s.validate(rules)
        if s.hp == 0:
            raise StateError("a knocked-out fighter cannot act")
        if act is Action.EXHAUSTED:
            raise PlanError("EXHAUSTED is never an intended action")
        if pw and (act not in ATTACKS or not s.power_available):
            raise PlanError("power needs an attack and an unspent power strike")

    prep = [_prepare(rules, s, act, pw) for s, act, pw in zip(snaps, intents, powers)]
    eff = (prep[0][0], prep[1][0])

    # 4. Base damage from the matrix, both looked up from effective actions.
    base = (rules.damage[eff[0]][eff[1]], rules.damage[eff[1]][eff[0]])

    # 5. Bonuses only turn positive base damage into more damage.
    dealt, opening_bonus, power_bonus = [], [], []
    for i in (0, 1):
        ob = rules.opening_damage if base[i] > 0 and snaps[i].opening else 0
        pb = rules.power_damage if base[i] > 0 and powers[i] and eff[i] is intents[i] else 0
        opening_bonus.append(ob)
        power_bonus.append(pb)
        dealt.append(base[i] + ob + pb)

    sides, nexts = [], []
    for i in (0, 1):
        s, own, opp = snaps[i], eff[i], eff[1 - i]
        _, cost, paid, stamina, power_available = prep[i]
        incoming = dealt[1 - i]

        # 6. Damage lands on both at once; clamp HP, keep the computed figure.
        hp = max(0, s.hp - incoming)

        # 7. Guard strain: a block that met a kick loses extra stamina, clamped.
        strain = min(stamina, rules.block_strain) if own is Action.BLOCK and opp is Action.KICK else 0
        stamina -= strain

        # 8. Recovery: one of three alternatives, then the cap.
        if own is Action.RECOVER:
            gain = rules.recover_hit if incoming > 0 else rules.recover_unhit
        elif own is Action.EXHAUSTED:
            gain = rules.exhausted_recovery
        else:
            gain = rules.ordinary_recovery
        after_recovery = min(rules.max_stamina, stamina + gain)

        # 9. The old opening always expires; a new one is earned two ways only.
        opening = int((own is Action.DUCK and opp in (Action.JAB, Action.THROW))
                      or (own is Action.JAB and dealt[i] > 0 and incoming == 0))

        # 10. Guard streak counts consecutive effective blocks, saturating.
        guard = min(rules.max_guard_streak, s.guard_streak + 1) if own is Action.BLOCK else 0

        nxt = FighterState(hp, after_recovery, opening, guard, power_available)
        nexts.append(nxt)
        sides.append(dict(
            before=s, after=nxt, intended=intents[i], effective=own, power=powers[i],
            cost=cost, cost_paid=paid, base_damage=base[i], opening_bonus=opening_bonus[i],
            power_bonus=power_bonus[i], bonus_damage=opening_bonus[i] + power_bonus[i],
            computed_damage=dealt[i], actual_hp_lost=s.hp - hp, strain=strain,
            recovered=after_recovery - stamina,
            reasons=_reasons(rules, s, nxt, intents[i], own, opp, powers[i],
                             base[i], dealt[i], incoming, strain)))

    # 11. Knockout is judged only after both halves are complete.
    ko = [n.hp == 0 for n in nexts]
    if all(ko):
        for side in sides:
            side["reasons"].append(Reason.DOUBLE_KO)
    else:
        for i in (0, 1):
            if ko[i]:
                sides[i]["reasons"].append(Reason.KO)
    trace = BeatTrace(index, *(SideTrace(**{**s, "reasons": tuple(s["reasons"])}) for s in sides))
    return nexts[0], nexts[1], trace


def terminal(a: FighterState, b: FighterState, final_round: bool) -> Outcome | None:
    if a.hp == 0 and b.hp == 0:
        return Outcome(None, Result.DOUBLE_KO)
    if a.hp == 0 or b.hp == 0:
        return Outcome("A" if b.hp == 0 else "B", Result.KO)
    if final_round:
        if a.hp == b.hp:
            return Outcome(None, Result.HP_TIE)
        return Outcome("A" if a.hp > b.hp else "B", Result.HP)
    return None


def resolve_round(rules: Ruleset, start: FightState, plan_a: Plan, plan_b: Plan) -> RoundResult:
    """Six beats from a nonterminal round-start state (docs/combat.md §7)."""
    if start.outcome is not None:
        raise StateError("the fight is already over")
    if type(start.round_index) is not int or not 0 <= start.round_index < rules.rounds:
        raise StateError(f"round_index {start.round_index!r} is outside 0..{rules.rounds - 1}")
    for s in (start.a, start.b):
        s.validate(rules)
        if s.hp == 0:
            raise StateError("a nonterminal round cannot start with zero HP")
    validate_plan(rules, start.a, plan_a)
    validate_plan(rules, start.b, plan_b)

    a, b = start.a, start.b
    last = start.round_index == rules.rounds - 1
    beats = []
    for i in range(rules.beats_per_round):
        a, b, trace = resolve_beat(rules, a, b, plan_a.actions[i], plan_b.actions[i],
                                   plan_a.power_slot == i, plan_b.power_slot == i, index=i)
        beats.append(trace)
        if a.hp == 0 or b.hp == 0:
            end = FightState(start.round_index, a, b, terminal(a, b, last))
            return RoundResult(start, plan_a, plan_b, tuple(beats), end)
    if last:
        end = FightState(start.round_index, a, b, terminal(a, b, True))
        return RoundResult(start, plan_a, plan_b, tuple(beats), end)
    ra = replace(a, stamina=min(rules.max_stamina, a.stamina + rules.break_recovery))
    rb = replace(b, stamina=min(rules.max_stamina, b.stamina + rules.break_recovery))
    end = FightState(start.round_index + 1, ra, rb)
    return RoundResult(start, plan_a, plan_b, tuple(beats), end,
                       (ra.stamina - a.stamina, rb.stamina - b.stamina))


def unexecuted(result: RoundResult) -> int:
    """How many revealed actions a knockout left unplayed; they are shown, never counted."""
    return len(result.plan_a.actions) - result.executed
