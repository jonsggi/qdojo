"""combat-v1 candidate 3: LAST STAND and FEINT (docs/combat.md §12), written
from the doc's hand vectors. Candidates 1 and 2 must keep refusing the new
actions and keep their numbers."""
import json

import pytest

from qdojo.combat import rules as rules_mod
from qdojo.combat.codec import decode_plan, encode_plan
from qdojo.combat.engine import new_fight, resolve_beat, resolve_round, validate_plan
from qdojo.combat.training import Contestant, run_fight, verify_replay
from qdojo.combat.types import Action as X, FighterState, FightState, Plan, PlanError, Reason

from .conftest import ROOT

J, K, B, D, T, R, LS, F = X.JAB, X.KICK, X.BLOCK, X.DUCK, X.THROW, X.RECOVER, X.LAST_STAND, X.FEINT


@pytest.fixture(scope="module")
def c3():
    return rules_mod.candidate_3()


def st(hp=120, stamina=48, opening=0, guard_streak=0, power_available=1):
    return FighterState(hp, stamina, opening, guard_streak, power_available)


def compact(s):
    return (s.hp, s.stamina, s.opening, s.guard_streak)


def reasons(t):
    return [r.value for r in t.reasons]


def test_artifact_ids_and_what_changed(c3):
    assert (ROOT / "docs/combat-v1-candidate-3.json").read_text() == \
        (rules_mod.RULESET_DIR / f"{rules_mod.CANDIDATE_3}.json").read_text()
    assert c3.digest.hex() == rules_mod.CANDIDATE_3_DIGEST
    assert c3.submitted == (0, 1, 2, 3, 4, 5, 7, 8) and c3.last_stand == (1, 16) and c3.max_opening == 2
    two = json.loads((ROOT / "docs/combat-v1-candidate-2.json").read_text())
    three = json.loads((ROOT / "docs/combat-v1-candidate-3.json").read_text())
    assert three["action_names"] == two["action_names"] + ["LAST_STAND", "FEINT"]
    assert [row[:7] for row in three["damage"][:7]] == two["damage"]          # the old 7x7 block is candidate 2
    assert {k for k in three if three[k] != two.get(k)} == {
        "semantic_version", "action_names", "submitted_action_ids", "base_costs", "damage", "last_stand"}


def test_released_rulesets_refuse_the_new_actions():
    for rules in (rules_mod.candidate_1(), rules_mod.candidate_2()):
        for a in (LS, F):
            with pytest.raises(PlanError):
                validate_plan(rules, st(100 if rules is rules_mod.candidate_1() else 120,
                                        60 if rules is rules_mod.candidate_1() else 48), Plan.of([a] * 6))


def test_feint_bait_and_guard_break(c3):
    a, b, t = resolve_beat(c3, st(), st(), F, B)
    assert (compact(a), compact(b)) == ((120, 48, 2, 0), (120, 46, 0, 1))
    assert reasons(t.a) == ["FEINT_BAITED", "OPENING_EARNED"]
    a2, b2, t2 = resolve_beat(c3, a, b, K, B)
    assert t2.a.computed_damage == 22 and t2.a.base_damage == 14 and t2.a.opening_bonus == 8
    assert reasons(t2.a) == ["HIT", "GUARD_BROKEN", "OPENING_USED"]
    assert compact(b2) == (98, 35, 0, 2)                                     # the strain still applies
    _, b3, t3 = resolve_beat(c3, a, b, LS, B)
    assert t3.a.computed_damage == 16 and compact(b3) == (104, 41, 0, 2)
    _, _, t4 = resolve_beat(c3, a, b, T, B)
    assert t4.a.computed_damage == 28 and Reason.GUARD_BROKEN not in t4.a.reasons   # a throw never needed it
    a5, b5, _ = resolve_beat(c3, st(), st(), F, D)
    assert (compact(a5), compact(b5)) == ((120, 48, 2, 0), (120, 46, 0, 0))    # the duck earns nothing


def test_feint_loses_to_any_strike_and_does_nothing_to_a_recovery(c3):
    a, b, t = resolve_beat(c3, st(), st(), F, J)
    assert (compact(a), compact(b)) == ((116, 48, 0, 0), (120, 44, 1, 0))
    assert resolve_beat(c3, st(), st(), F, K)[2].a.actual_hp_lost == 8
    assert resolve_beat(c3, st(), st(), F, T)[2].a.actual_hp_lost == 8
    a, b, _ = resolve_beat(c3, st(), st(), F, R)
    assert (compact(a), compact(b)) == ((120, 48, 0, 0), (120, 48, 0, 0))
    a, b, _ = resolve_beat(c3, st(), st(), F, F)
    assert (compact(a), compact(b)) == ((120, 48, 0, 0), (120, 48, 0, 0))


def test_last_stand(c3):
    a, b, t = resolve_beat(c3, st(hp=80), st(hp=110), LS, J)
    assert (compact(a), compact(b)) == ((72, 42, 0, 0), (86, 44, 0, 0))
    assert t.a.stand_bonus == 16 and t.a.bonus_damage == 16 and reasons(t.a) == ["HIT", "STAND_BONUS"]
    assert resolve_beat(c3, st(hp=105), st(hp=110), LS, J)[2].a.computed_damage == 13
    assert resolve_beat(c3, st(hp=110), st(hp=80), LS, J)[2].a.computed_damage == 8
    _, _, t = resolve_beat(c3, st(hp=80), st(hp=110), LS, B)
    assert t.a.computed_damage == 0 and t.a.stand_bonus == 0 and reasons(t.a) == ["BLOCKED"]
    _, _, t = resolve_beat(c3, st(hp=80), st(hp=110), LS, K)
    assert (t.a.computed_damage, t.b.computed_damage) == (24, 14)
    _, _, t = resolve_beat(c3, st(hp=110), st(hp=80), T, LS)
    assert t.a.computed_damage == 0 and reasons(t.a) == ["THROW_INTERRUPTED"] and t.b.computed_damage == 24
    _, _, t = resolve_beat(c3, st(hp=80, opening=1), st(hp=110), LS, D)
    assert t.a.computed_damage == 8 + 16 + 8                                  # it hits a duck; the opening adds
    with pytest.raises(PlanError):
        Plan.of([LS] * 6, 0)


def test_codec_and_traces(c3):
    plan = Plan.of([LS, F, J, K, B, D], 2)
    assert encode_plan(plan).hex() == "07080001020302" and decode_plan(encode_plan(plan)) == plan
    _, _, t = resolve_beat(c3, st(), st(), J, J)
    assert "stand_bonus" in t.a.to_json()
    _, _, t = resolve_beat(rules_mod.candidate_2(), st(), st(), J, J)
    assert "stand_bonus" not in t.a.to_json()                                 # old replays keep their shape


def test_a_candidate_3_fight_and_replay(c3):
    replay = run_fight(Contestant("p", npc="scout-v1"), Contestant("q", npc="mixed-v1"), bytes(32), 1, c3)
    assert replay["ruleset_digest"] == rules_mod.CANDIDATE_3_DIGEST
    assert verify_replay(replay) == replay["outcome"]
    s = FightState(2, st(hp=40), st(hp=90))
    res = resolve_round(c3, s, Plan.of([F, K, LS, R, LS, B]), Plan.of([B, B, J, J, J, J]))
    assert res.beats[1].a.reasons[:2] == (Reason.HIT, Reason.GUARD_BROKEN)
    assert new_fight(c3).a == st()


def test_demo_c3_profile_and_prompts(c3, tmp_path):
    from qdojo.combat import devnet, llm_planner as L
    m, m2 = devnet.manifest("demo-c3"), devnet.manifest("demo-c2")
    assert m.ruleset is c3 and m.timing == m2.timing and m.tiers == m2.tiers and m.fees == m2.fees
    net = devnet.Devnet(tmp_path / "a", "demo-c3")
    meta = json.loads((tmp_path / "a" / devnet.MARKER).read_text())
    assert devnet.recorded(meta)[2] == net.m
    obs = {"ruleset_digest": rules_mod.CANDIDATE_3_DIGEST}
    assert L.prompt_for(L.PROMPT, obs).name == "planner-system-candidate-3.md"
    assert L.prompt_for(L.PROMPTS / "planner-system-claude.md", obs).name == "planner-system-claude-candidate-3.md"
    for name in ("planner-system-candidate-3.md", "planner-system-claude-candidate-3.md"):
        text = (L.PROMPTS / name).read_text()
        assert "LAST_STAND" in text and "FEINT" in text and "candidate 3" in text
