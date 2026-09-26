"""combat-v1 candidate 2: the hand vectors of docs/combat.md "Candidate 2",
written from the doc, and generated fights against the independent reference
in docs/reference/combat_v1.py pointed at docs/combat-v1-candidate-2.json.

Candidate 1 keeps its own vectors (test_vectors.py); both rulesets load side
by side, and each digest names exactly one set of numbers.
"""
import json
import random

import pytest

from qdojo.combat import rules as rules_mod
from qdojo.combat.engine import new_fight, resolve_beat, resolve_round
from qdojo.combat.training import Contestant, run_fight, verify_replay
from qdojo.combat.types import ATTACKS, SUBMITTED, Action as X, FighterState, Plan, Reason, Result

from .conftest import ROOT

J, K, B, D, T, R = X.JAB, X.KICK, X.BLOCK, X.DUCK, X.THROW, X.RECOVER


@pytest.fixture(scope="module")
def c2():
    return rules_mod.candidate_2()


def st(hp=120, stamina=60, opening=0, guard_streak=0, power_available=1):
    return FighterState(hp, stamina, opening, guard_streak, power_available)


def compact(s):
    return (s.hp, s.stamina, s.opening, s.guard_streak)


def test_artifacts_agree_and_candidate_1_is_untouched(c2):
    assert (ROOT / "docs/combat-v1-candidate-2.json").read_text() == \
        (rules_mod.RULESET_DIR / f"{rules_mod.CANDIDATE_2}.json").read_text()
    assert c2.digest.hex() == rules_mod.CANDIDATE_2_DIGEST
    assert rules_mod.candidate_1().digest.hex() == rules_mod.CANDIDATE_1_DIGEST
    assert rules_mod.by_digest(rules_mod.CANDIDATE_1_DIGEST) is rules_mod.candidate_1()
    assert rules_mod.by_digest(bytes.fromhex(rules_mod.CANDIDATE_2_DIGEST)) is c2
    with pytest.raises(rules_mod.RulesetError):
        rules_mod.by_digest("00" * 32)
    # Only the documented numbers differ from candidate 1.
    one = json.loads((ROOT / "docs/combat-v1.json").read_text())
    two = json.loads((ROOT / "docs/combat-v1-candidate-2.json").read_text())
    diff = {k for k in one if one[k] != two[k]}
    assert diff == {"semantic_version", "initial", "limits", "damage", "opening_damage", "power_damage"}
    cells = {(i, k) for i in range(7) for k in range(7) if one["damage"][i][k] != two["damage"][i][k]}
    assert cells == {(J, K), (K, J), (D, J), (T, B)}


ONE_BEAT = [
    (J, B, (120, 56, 0, 0), (120, 58, 0, 1)),
    (J, K, (116, 56, 0, 0), (110, 50, 0, 0)),     # jab wins the exchange 10 to 4
    (D, J, (120, 58, 1, 0), (116, 56, 0, 0)),     # duck counters for 4 and earns an opening
    (K, D, (120, 50, 0, 0), (102, 58, 0, 0)),
    (T, B, (120, 53, 0, 0), (100, 58, 0, 1)),     # throw breaks a block for 20
    (B, K, (120, 52, 0, 1), (120, 50, 0, 0)),
    (R, J, (108, 60, 0, 0), (120, 56, 1, 0)),
    (T, T, (120, 53, 0, 0), (120, 53, 0, 0)),
]


@pytest.mark.parametrize("xa,xb,ea,eb", ONE_BEAT, ids=lambda v: v.name if isinstance(v, X) else None)
def test_one_beat_table(c2, xa, xb, ea, eb):
    a, b, _ = resolve_beat(c2, st(), st(), xa, xb)
    assert (compact(a), compact(b)) == (ea, eb)
    b2, a2, _ = resolve_beat(c2, st(), st(), xb, xa)
    assert (a2, b2) == (a, b)


def test_duck_counter_then_kick(c2):
    a, b, t1 = resolve_beat(c2, st(), st(), D, J)
    assert t1.a.computed_damage == 4 and Reason.HIT in t1.a.reasons and Reason.EVADED in t1.b.reasons
    assert Reason.OPENING_EARNED in t1.a.reasons
    a, b, t2 = resolve_beat(c2, a, b, K, J)
    assert (compact(a), compact(b)) == ((110, 48, 0, 0), (104, 52, 0, 0))
    assert (t2.a.base_damage, t2.a.opening_bonus, t2.a.computed_damage, t2.b.computed_damage) == (4, 8, 12, 10)


def test_powered_kick_into_duck_with_opening(c2):
    a, b, t = resolve_beat(c2, st(opening=1), st(), K, D, True, False)
    assert a.stamina == 46 and a.power_available == 0
    assert t.b.actual_hp_lost == 38 and b.hp == 82          # 18 + 8 opening + 12 power
    assert Reason.POWER_USED in t.a.reasons and Reason.OPENING_USED in t.a.reasons


def test_duck_counter_takes_an_opening_but_never_power(c2):
    _, b, t = resolve_beat(c2, st(opening=1), st(), D, J)
    assert t.a.computed_damage == 12 and b.hp == 108
    with pytest.raises(Exception):
        Plan.of([D] * 6, 0)


def test_unaffordable_kick_is_exhausted(c2):
    a, b, t = resolve_beat(c2, st(stamina=11), st(), K, J)
    assert t.a.effective is X.EXHAUSTED
    assert (compact(a), compact(b)) == ((108, 17, 0, 0), (120, 56, 1, 0))


def test_six_jabs_each_round(c2):
    s = new_fight(c2)
    r = resolve_round(c2, s, Plan.of([J] * 6), Plan.of([J] * 6))
    assert (r.end.a.hp, r.end.a.stamina, r.end.b.hp) == (72, 46, 72)
    r = resolve_round(c2, r.end, Plan.of([J] * 6), Plan.of([J] * 6))
    assert (r.end.a.hp, r.end.a.stamina) == (24, 32)
    r = resolve_round(c2, r.end, Plan.of([J] * 6), Plan.of([J] * 6))
    assert r.executed == 3 and r.end.outcome.result is Result.DOUBLE_KO


def test_recovering_all_fight_ties_at_120(c2):
    s = new_fight(c2)
    for _ in range(3):
        s = resolve_round(c2, s, Plan.of([R] * 6), Plan.of([R] * 6)).end
    assert (s.a.hp, s.b.hp, s.outcome.result) == (120, 120, Result.HP_TIE)


def test_state_limits_follow_the_ruleset(c2):
    FighterState(120, 60, 0, 0, 1).validate(c2)
    with pytest.raises(Exception):
        FighterState(120, 60, 0, 0, 1).validate(rules_mod.candidate_1())


@pytest.fixture()
def reference_c2(reference):
    saved = reference.RULES
    reference.RULES = json.loads((ROOT / "docs/combat-v1-candidate-2.json").read_text())
    yield reference
    reference.RULES = saved


def test_generated_fights_match_the_reference(c2, reference_c2):
    ref = reference_c2
    rng = random.Random(0xC2)
    ref_state = lambda s: ref.State(s.hp, s.stamina, s.opening, s.guard_streak, s.power_available)

    def plan(state):
        actions = [rng.choice(SUBMITTED) for _ in range(6)]
        slots = [i for i, a in enumerate(actions) if a in ATTACKS]
        slot = rng.choice([-1] + slots) if state.power_available and slots and rng.random() < 0.5 else -1
        return Plan.of(actions, slot)
    for _ in range(1000):
        state = new_fight(c2)
        while state.outcome is None:
            pa, pb = plan(state.a), plan(state.b)
            res = resolve_round(c2, state, pa, pb)
            got = ref.resolve_round((ref_state(state.a), ref_state(state.b)),
                                    (([int(x) for x in pa.actions], pa.power_slot),
                                     ([int(x) for x in pb.actions], pb.power_slot)), state.round_index)
            assert (got[0][0], got[0][1]) == (ref_state(res.end.a), ref_state(res.end.b))
            assert len(got[1]) == res.executed
            assert got[2] == (None if res.end.outcome is None else (res.end.outcome.winner or "DRAW"))
            state = res.end


def test_a_candidate_2_replay_verifies_by_its_own_digest(c2):
    replay = run_fight(Contestant("p", npc="scout-v1"), Contestant("q", npc="mixed-v1"), bytes(32), 1, c2)
    assert replay["ruleset_digest"] == rules_mod.CANDIDATE_2_DIGEST
    assert verify_replay(replay) == replay["outcome"]            # picks candidate 2 from the digest
    replay_c1 = run_fight(Contestant("p", npc="scout-v1"), Contestant("q", npc="mixed-v1"), bytes(32), 1)
    assert verify_replay(replay_c1) == replay_c1["outcome"]


def test_llm_planner_reads_the_ruleset_it_is_playing(c2):
    from qdojo.combat import llm_planner as L
    obs2 = {"ruleset_digest": rules_mod.CANDIDATE_2_DIGEST}
    assert L.prompt_for(L.PROMPT, obs2).name == "planner-system-candidate-2.md"
    assert L.prompt_for(L.PROMPTS / "planner-system-claude.md", obs2).name == "planner-system-claude-candidate-2.md"
    assert L.prompt_for(L.PROMPT, {"ruleset_digest": rules_mod.CANDIDATE_1_DIGEST}) == L.PROMPT
    assert L._rules(obs2) is c2 and L._rules({}) is rules_mod.candidate_1()
    for name in ("planner-system-candidate-2.md", "planner-system-claude-candidate-2.md"):
        text = (L.PROMPTS / name).read_text()
        assert "candidate 2" in text and "120" in text and "+12" in text and "+8" in text
