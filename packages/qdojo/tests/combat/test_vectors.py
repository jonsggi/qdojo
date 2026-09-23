"""Every hand-checkable vector in docs/combat.md §8, written from the doc, not from the engine."""
import pytest

from qdojo.combat.engine import new_fight, resolve_beat, resolve_round, unexecuted
from qdojo.combat.types import (
    Action as X, FighterState, FightState, Plan, PlanError, Reason, Result, StateError,
)

J, K, B, D, T, R = X.JAB, X.KICK, X.BLOCK, X.DUCK, X.THROW, X.RECOVER


def st(hp=100, stamina=60, opening=0, guard_streak=0, power_available=1):
    return FighterState(hp, stamina, opening, guard_streak, power_available)


def compact(s):
    return (s.hp, s.stamina, s.opening, s.guard_streak)


ONE_BEAT = [
    (J, B, (100, 56, 0, 0), (100, 58, 0, 1)),
    (J, K, (86, 56, 0, 0), (92, 50, 0, 0)),
    (D, J, (100, 58, 1, 0), (100, 56, 0, 0)),
    (K, D, (100, 50, 0, 0), (82, 58, 0, 0)),
    (T, B, (100, 53, 0, 0), (86, 58, 0, 1)),
    (B, K, (100, 52, 0, 1), (100, 50, 0, 0)),
    (R, J, (88, 60, 0, 0), (100, 56, 1, 0)),
    (T, T, (100, 53, 0, 0), (100, 53, 0, 0)),
]


@pytest.mark.parametrize("xa,xb,ea,eb", ONE_BEAT, ids=lambda v: v.name if isinstance(v, X) else None)
def test_one_beat_table(rules, xa, xb, ea, eb):
    a, b, _ = resolve_beat(rules, st(), st(), xa, xb)
    assert (compact(a), compact(b)) == (ea, eb)


def test_opening_carries_into_the_next_beat(rules):
    a, b, _ = resolve_beat(rules, st(), st(), D, J)
    a, b, trace = resolve_beat(rules, a, b, K, J)
    assert (compact(a), compact(b)) == ((92, 48, 0, 0), (82, 52, 0, 0))
    assert trace.a.computed_damage == 18 and Reason.OPENING_USED in trace.a.reasons


def test_unaffordable_kick_is_exhausted(rules):
    a, b, trace = resolve_beat(rules, st(stamina=11), st(), K, J)
    assert (compact(a), compact(b)) == ((88, 17, 0, 0), (100, 56, 1, 0))
    assert trace.a.effective is X.EXHAUSTED and trace.a.cost == 12 and trace.a.cost_paid == 0
    assert Reason.INSUFFICIENT_STAMINA in trace.a.reasons


def test_exact_stamina_executes(rules):
    a, _, trace = resolve_beat(rules, st(stamina=12), st(), K, R)
    assert a.stamina == 2 and trace.a.effective is K


def test_powered_kick_with_opening_into_duck(rules):
    a, b, _ = resolve_beat(rules, st(opening=1), st(), K, D, power_a=True)
    assert a.stamina == 46 and a.power_available == 0
    assert b.hp == 74 and a.hp == 100


def test_powered_jab_into_block_is_spent_and_harmless(rules):
    a, b, trace = resolve_beat(rules, st(), st(), J, B, power_a=True)
    assert a.stamina == 52 and a.power_available == 0 and b.hp == 100
    assert Reason.POWER_WASTED in trace.a.reasons


def test_exhausted_power_is_still_spent(rules):
    a, _, _ = resolve_beat(rules, st(stamina=9), st(), J, J, power_a=True)
    assert a.hp == 88 and a.stamina == 15 and a.power_available == 0


def test_guard_fatigue(rules):
    a, b = st(), st()
    seen = []
    for _ in range(4):
        a, b, _ = resolve_beat(rules, a, b, B, R)
        seen.append((a.stamina, a.guard_streak))
    assert seen == [(58, 1), (53, 2), (45, 3), (34, 3)]
    a2, _, trace = resolve_beat(rules, a, b, B, R)
    assert trace.a.cost == 13


def test_block_at_four_into_kick(rules):
    a, b, trace = resolve_beat(rules, st(stamina=4), st(), B, K)
    assert a == st(stamina=2, guard_streak=1)
    assert trace.a.strain == 0 and Reason.GUARD_STRAIN in trace.a.reasons
    _, _, nxt = resolve_beat(rules, a, b, B, R)
    assert nxt.a.cost == 7 and nxt.a.effective is X.EXHAUSTED


def test_simultaneous_ko_equal(rules):
    a, b, trace = resolve_beat(rules, st(hp=8), st(hp=8), J, J)
    assert a.hp == b.hp == 0
    assert trace.a.computed_damage == trace.b.computed_damage == 8
    assert Reason.DOUBLE_KO in trace.a.reasons and Reason.DOUBLE_KO in trace.b.reasons


def test_simultaneous_ko_unequal(rules):
    start = FightState(0, st(hp=14), st(hp=8))
    res = resolve_round(rules, start, Plan.of([J] * 6), Plan.of([K] * 6))
    assert res.end.outcome.winner is None and res.end.outcome.result is Result.DOUBLE_KO
    assert res.executed == 1 and unexecuted(res) == 5


def test_three_rounds_of_recovery_is_a_tie(rules):
    state = new_fight(rules)
    rest = Plan.of([R] * 6)
    for _ in range(3):
        res = resolve_round(rules, state, rest, rest)
        state = res.end
    assert state.a == state.b == st()
    assert state.outcome.winner is None and state.outcome.result is Result.HP_TIE


def test_six_jabs_every_round(rules):
    jabs = Plan.of([J] * 6)
    r0 = resolve_round(rules, new_fight(rules), jabs, jabs)
    assert r0.beats[-1].a.after == st(hp=52, stamina=36)
    assert r0.end.a == st(hp=52, stamina=46) and r0.break_recovery == (10, 10)
    r1 = resolve_round(rules, r0.end, jabs, jabs)
    assert r1.beats[-1].a.after.stamina == 22
    assert r1.end.a == st(hp=4, stamina=32) and r1.end.round_index == 2
    r2 = resolve_round(rules, r1.end, jabs, jabs)
    assert r2.executed == 1 and r2.end.outcome.result is Result.DOUBLE_KO


def test_state_carries_through_the_break(rules):
    """combat.md §8's (55,1,3) vector is not reachable in one fighter (an opening
    needs DUCK/JAB, a streak needs BLOCKs), so check each carry on its own side:
    A ends on DUCK-vs-JAB (opening), B ends on four BLOCKs (streak 3)."""
    res = resolve_round(rules, new_fight(rules),
                        Plan.of([R, R, R, R, R, D]), Plan.of([R, R, B, B, B, J]))
    last = res.beats[-1]
    assert last.a.after.opening == 1 and last.b.after.guard_streak == 0
    assert res.end.a.opening == 1 and res.end.round_index == 1
    assert res.end.a.stamina == min(60, last.a.after.stamina + 10)
    res = resolve_round(rules, new_fight(rules), Plan.of([R] * 6), Plan.of([R, R, B, B, B, B]))
    assert res.beats[-1].b.after.guard_streak == 3 and res.end.b.guard_streak == 3
    assert res.end.b.stamina == min(60, res.beats[-1].b.after.stamina + 10)


def test_power_after_ko_is_not_executed(rules):
    start = FightState(0, st(), st(hp=8))
    plan_a = Plan.of([J, J, K, J, J, J], power_slot=3)
    res = resolve_round(rules, start, plan_a, Plan.of([R] * 6))
    assert res.executed == 1
    assert res.end.a.power_available == 1 and res.end.outcome.winner == "A"


@pytest.mark.parametrize("actions,slot", [
    ([J] * 5, -1), ([J] * 7, -1), ([J] * 5 + ["EXHAUSTED"], -1), ([J] * 5 + [9], -1),
    ([J] * 6, 6), ([J] * 6, -2), ([B] * 6, 0), (["jab"] * 6, -1),
])
def test_malformed_plans_are_rejected(actions, slot):
    with pytest.raises(PlanError):
        Plan.of(actions, slot)


def test_spent_power_rejects_the_whole_plan(rules):
    start = FightState(1, st(power_available=0), st())
    with pytest.raises(PlanError):
        resolve_round(rules, start, Plan.of([R] * 5 + [J], power_slot=5), Plan.of([R] * 6))


@pytest.mark.parametrize("bad", [
    st(hp=101), st(stamina=61), st(stamina=-1), st(opening=2), st(guard_streak=4), st(power_available=2),
    FighterState(True, 60, 0, 0, 1),
])
def test_impossible_state_is_rejected_not_clamped(rules, bad):
    with pytest.raises(StateError):
        resolve_beat(rules, bad, st(), J, J)


def test_no_extra_rounds_and_no_play_after_ko(rules):
    with pytest.raises(StateError):
        resolve_round(rules, FightState(3, st(), st()), Plan.of([R] * 6), Plan.of([R] * 6))
    with pytest.raises(StateError):
        resolve_round(rules, FightState(0, st(hp=0), st()), Plan.of([R] * 6), Plan.of([R] * 6))
