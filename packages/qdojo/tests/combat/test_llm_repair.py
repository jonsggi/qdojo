import pytest

from qdojo.combat import llm_planner, planner


def plan_of(reply):
    plan, _ = llm_planner._model_plan(reply)
    return plan


def test_lowercase_and_spacing_are_repaired():
    p = plan_of('{"actions": ["jab", "Kick", " block ", "duck", "throw", "recover"], "power_slot": -1}')
    assert p.power_slot == -1 and len(p.actions) == 6


def test_power_named_action_becomes_the_power_slot():
    p = plan_of('{"actions": ["JAB", "POWER JAB", "BLOCK", "DUCK", "THROW", "RECOVER"], "power_slot": -1}')
    assert p.power_slot == 1


def test_power_on_a_defensive_move_is_dropped_not_fatal():
    p = plan_of('{"actions": ["JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER"], "power_slot": 3}')
    assert p.power_slot == -1


def test_missing_power_slot_means_none_and_string_slot_is_read():
    assert plan_of('{"actions": ["JAB","JAB","JAB","JAB","JAB","JAB"]}').power_slot == -1
    assert plan_of('{"actions": ["JAB","JAB","KICK","JAB","JAB","JAB"], "power_slot": "2"}').power_slot == 2


def test_a_reply_without_a_plan_still_fails():
    with pytest.raises(planner.PlannerError):
        plan_of("I think I will jab a lot.")
    with pytest.raises(planner.PlannerError):
        plan_of('{"actions": ["JAB", "UPPERCUT", "BLOCK", "DUCK", "THROW", "RECOVER"], "power_slot": -1}')
