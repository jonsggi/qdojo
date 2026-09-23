"""Generated fights: symmetry, ranges, conservation, determinism, and agreement with
the independent reference in docs/reference/combat_v1.py.

QDOJO_COMBAT_CASES sets the number of generated fights (default 2,000; the
release gate in docs/model.md asks for at least 100,000).
"""
import hashlib
import os
import random

from qdojo.combat.engine import new_fight, resolve_beat, resolve_round
from qdojo.combat.types import ATTACKS, SUBMITTED, Action, FighterState, Plan

CASES = int(os.environ.get("QDOJO_COMBAT_CASES", "2000"))


def _plan(rng, state):
    actions = [rng.choice(SUBMITTED) for _ in range(6)]
    slots = [i for i, a in enumerate(actions) if a in ATTACKS]
    slot = rng.choice([-1] + slots) if state.power_available and slots and rng.random() < 0.5 else -1
    return Plan.of(actions, slot)


def _flip_round(res):
    """The same round with A and B exchanged, as a comparable structure."""
    return [(b.b, b.a) for b in res.beats]


def _check_side(rules, side, other):
    before, after = side.before, side.after
    after.validate(rules)
    assert side.actual_hp_lost == before.hp - after.hp
    assert other.computed_damage >= side.actual_hp_lost
    assert after.stamina == before.stamina - side.cost_paid - side.strain + side.recovered
    assert side.cost_paid in (0, side.cost)
    assert (side.cost_paid == 0 and side.cost > 0) == (side.effective is Action.EXHAUSTED) or side.cost == 0
    if side.base_damage == 0:
        assert side.computed_damage == 0


def test_generated_fights(rules, reference):
    rng = random.Random(0xC0B7A7)
    ref_state = lambda s: reference.State(s.hp, s.stamina, s.opening, s.guard_streak, s.power_available)
    for _ in range(CASES):
        state = new_fight(rules)
        while state.outcome is None:
            pa, pb = _plan(rng, state.a), _plan(rng, state.b)
            res = resolve_round(rules, state, pa, pb)
            again = resolve_round(rules, state, pa, pb)
            assert res == again

            swapped = resolve_round(rules, type(state)(state.round_index, state.b, state.a), pb, pa)
            assert [(b.a, b.b) for b in swapped.beats] == _flip_round(res)
            assert (swapped.end.a, swapped.end.b) == (res.end.b, res.end.a)
            if res.end.outcome:
                w = res.end.outcome.winner
                assert swapped.end.outcome.winner == {"A": "B", "B": "A", None: None}[w]

            for beat in res.beats:
                _check_side(rules, beat.a, beat.b)
                _check_side(rules, beat.b, beat.a)

            ref = reference.resolve_round(
                (ref_state(state.a), ref_state(state.b)),
                (([int(x) for x in pa.actions], pa.power_slot), ([int(x) for x in pb.actions], pb.power_slot)),
                state.round_index)
            assert (ref[0][0], ref[0][1]) == (ref_state(res.end.a), ref_state(res.end.b))
            assert len(ref[1]) == res.executed
            ref_result = ref[2]
            if res.end.outcome is None:
                assert ref_result is None
            else:
                assert ref_result == (res.end.outcome.winner or "DRAW")
            state = res.end


def test_every_intent_pair_in_boundary_states_matches_reference(rules, reference):
    count = 0
    staminas = sorted({0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 60})
    for sa in staminas:
        for sb in staminas:
            for opening in (0, 1):
                for guard in (0, 3):
                    for xa in SUBMITTED:
                        for xb in SUBMITTED:
                            for pa in ((False, True) if xa in ATTACKS else (False,)):
                                a = FighterState(9, sa, opening, guard, 1)
                                b = FighterState(12, sb, 0, 0, 1)
                                na, nb, tr = resolve_beat(rules, a, b, xa, xb, pa, False)
                                mb, ma, rt = resolve_beat(rules, b, a, xb, xa, False, pa)
                                assert (na, nb) == (ma, mb) and (tr.a, tr.b) == (rt.b, rt.a)
                                (ra, rb), _ = reference.beat(
                                    reference.State(*a.__dict__.values()), reference.State(*b.__dict__.values()),
                                    int(xa), int(xb), pa, False)
                                assert (tuple(ra.__dict__.values()), tuple(rb.__dict__.values())) == \
                                    (tuple(na.__dict__.values()), tuple(nb.__dict__.values()))
                                count += 1
    assert count == 14 * 14 * 2 * 2 * (3 * 2 + 3) * 6   # 42,336 paired cases


def test_resolution_uses_no_hidden_randomness(rules):
    """Same inputs under a disturbed global RNG and hash seed give the same bytes."""
    plan = Plan.of([Action.JAB, Action.DUCK, Action.KICK, Action.RECOVER, Action.BLOCK, Action.THROW], 2)
    first = resolve_round(rules, new_fight(rules), plan, plan)
    random.seed(os.urandom(8))
    hashlib.sha256(os.urandom(8))
    assert resolve_round(rules, new_fight(rules), plan, plan) == first
