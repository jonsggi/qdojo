"""Candidate-3 PROTOTYPE (docs/proposals/candidate-3-moves.md): LAST_STAND in the
Python engine behind trial rulesets. Candidate 1 and 2 must not change."""
import pytest

from qdojo.combat import rules as R
from qdojo.combat.engine import new_fight, resolve_beat, resolve_round, validate_plan
from qdojo.combat.types import Action as X, FighterState, FightState, Plan, PlanError

LS = X.LAST_STAND


def st(hp=120, stamina=48, opening=0):
    return FighterState(hp, stamina, opening, 0, 1)


@pytest.fixture(scope="module")
def ta():
    return R.by_version("combat-v1-candidate-3-trial-a")


def test_trials_load_and_released_rulesets_refuse_the_new_action(ta):
    assert ta.submitted == (0, 1, 2, 3, 4, 5, 7) and ta.last_stand == (1, 16, 2)
    assert ta.digest.hex() not in R.KNOWN.values()
    with pytest.raises(PlanError):
        validate_plan(R.candidate_2(), st(), Plan.of([LS] * 6))
    with pytest.raises(PlanError):
        Plan.of([LS] * 6, 0)                        # never powered


def test_bonus_only_when_behind_and_only_from_its_round(ta):
    behind, ahead = st(hp=60), st(hp=100)
    _, _, t = resolve_beat(ta, behind, ahead, LS, X.JAB, round_index=2)
    assert t.a.computed_damage == 8 + 16 and t.b.computed_damage == 8      # capped at +16 (40 behind)
    _, _, t = resolve_beat(ta, st(hp=95), ahead, LS, X.JAB, round_index=2)
    assert t.a.computed_damage == 8 + 5
    _, _, t = resolve_beat(ta, behind, ahead, LS, X.JAB, round_index=1)
    assert t.a.computed_damage == 8                                         # trial a: final round only
    _, _, t = resolve_beat(ta, ahead, behind, LS, X.JAB, round_index=2)
    assert t.a.computed_damage == 8                                         # never when ahead
    _, _, t = resolve_beat(ta, behind, ahead, LS, X.BLOCK, round_index=2)
    assert t.a.computed_damage == 0 and "BLOCKED" in [r.value for r in t.a.reasons]
    _, _, t = resolve_beat(ta, st(hp=60, opening=1), ahead, LS, X.DUCK, round_index=2)
    assert t.a.computed_damage == 8 + 16 + 8                                # opening applies; duck is hit
    _, _, t = resolve_beat(ta, behind, ahead, LS, X.KICK, round_index=2)
    assert t.b.computed_damage == 14 and t.a.computed_damage == 24         # a kick still trades into it


def test_a_trial_fight_runs_end_to_end(ta):
    s = new_fight(ta)
    s = FightState(2, st(hp=50), st(hp=90))
    res = resolve_round(ta, s, Plan.of([LS, X.JAB, LS, X.RECOVER, LS, X.BLOCK]), Plan.of([X.JAB] * 6))
    assert res.beats[0].a.computed_damage == 8 + 16
