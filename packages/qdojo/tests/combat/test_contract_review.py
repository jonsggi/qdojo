"""Regression tests for findings from the C++ port's review of the reference contract."""
from qdojo.combat.codec import Code, Op
from qdojo.combat.contract import development_manifest
from qdojo.combat.rules import candidate_1
from qdojo.combat.sim import World, identity

from .test_contract import (  # noqa: F401  (world is a fixture)
    ADMIN, DEV, HOUSE, SHARE, Player, _cup, world,
)


def test_strangers_cannot_take_nonce_slots(world):  # noqa: F811
    a = Player(world, "a")
    r = a.enter()
    world.send(a.owner, Op.QUEUE_CANCEL, offer_id=r.data["offer_id"])
    stranger = identity("stranger")
    before = set(world.contract.accounts)
    assert world.send(stranger, Op.WITHDRAW).code == Code.NOT_OWNER
    assert world.send(stranger, Op.QUEUE_CANCEL, offer_id=r.data["offer_id"]).code == Code.NOT_OWNER
    assert stranger not in world.contract.nonces and world.contract.accounts == before
    world.check_conservation()


def test_advance_requires_nonce_zero(world):  # noqa: F811
    a = Player(world, "a")
    r = a.enter()
    assert world.send(a.owner, Op.ADVANCE, target_kind=1, target_id=r.data["offer_id"]).code == Code.OK
    assert world.send(a.owner, Op.ADVANCE, nonce=5, target_kind=1,
                      target_id=r.data["offer_id"]).code == Code.BAD_BODY


def test_account_capacity_rejects_before_taking_funds():
    w = World(development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE, max_accounts=6))
    w.mint(ADMIN, 10**9)
    a, b = Player(w, "a"), Player(w, "b")   # admin + 3 fee recipients + 2 owners = 6: full
    assert a.enter().ok and b.enter().ok    # existing slots: fine
    late_fid, late_owner = identity("fighter:late"), identity("owner:late")
    w.owners[late_fid] = late_owner
    w.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=late_fid, registry_version=1, house_npc=0)
    res = w.send(late_owner, Op.REGISTER_FIGHTER, fighter_id=late_fid, registry_version=1)
    assert res.code == Code.FULL and late_fid not in w.contract.fighters
    w.check_conservation()


def test_cup_windows_must_be_reachable(world):  # noqa: F811
    c = world.contract
    base = dict(ruleset_digest=c.m.ruleset.digest, timing_profile_id=1, fee_profile_id=1, entry_fee=2000,
                registration_close=world.tick + 50, min_entrants=4, max_entrants=16, level_ticks=3000,
                first_level_delay=120, checkin_ticks=120, replay_delay=120)
    for bad in ({"checkin_ticks": 0}, {"first_level_delay": 1}, {"replay_delay": 0}):
        assert world.send(ADMIN, Op.ADMIN_CREATE_CUP, **{**base, **bad}).code == Code.BAD_BODY
    assert world.send(ADMIN, Op.ADMIN_CREATE_CUP, **base).ok


def test_cup_check_in_observes_cooldown(world):  # noqa: F811
    cup = _cup(world, close_in=50)
    players = [Player(world, f"k{i}") for i in range(4)]
    for p in players:
        assert world.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1).ok
    world.run_until(cup.descriptor["registration_close"] + 1)
    faulty = players[0]
    faulty.f.cooldown_until = cup.level_start + 1000      # as if it faulted in a duel just before
    world.run_until(cup.level_start)
    pairing = next(p for p in cup.pairings.values() if faulty.fid in (p.a, p.b))
    r = world.send(faulty.operator, Op.CUP_CHECK_IN, cup_id=cup.cup_id, pairing_id=pairing.pairing_id,
                   fighter_id=faulty.fid, auth_version=1)
    assert r.code == Code.COOLDOWN
    kinds = [e[2] for e in world.contract.events]
    other = next(x for x in (pairing.a, pairing.b) if x != faulty.fid)
    pl = next(p for p in players if p.fid == other)
    assert world.send(pl.operator, Op.CUP_CHECK_IN, cup_id=cup.cup_id, pairing_id=pairing.pairing_id,
                      fighter_id=other, auth_version=1).ok
    assert [e[2] for e in world.contract.events][len(kinds):] == ["CUP_CHECKED_IN"]
    world.check_conservation()
