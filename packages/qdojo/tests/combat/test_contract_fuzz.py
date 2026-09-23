"""Random traffic against the reference contract; invariants checked every tick.

Players enter, cancel, duel, commit, reveal (sometimes wrongly or late),
withdraw, send garbage and transfer fighters; service gaps are injected.
After every tick: QU is conserved, the balance equals the liabilities, every
fighter holds at most one lock and every lock points at a live object.
"""
import os
import random

from qdojo.combat.codec import Code, Op
from qdojo.combat.types import SUBMITTED, Plan
from qdojo.combat.sim import commit_fields, identity, reveal_fields

from .test_contract import ADMIN, Player, world  # noqa: F401  (fixture)

TICKS = int(os.environ.get("QDOJO_COMBAT_FUZZ_TICKS", "3000"))


def _check_locks(w):
    c = w.contract
    for f in c.fighters.values():
        if f.lock in ("QUEUED", "DUEL_OFFER"):
            o = c.offers[f.lock_ref]
            assert o.status == "OPEN" and o.fighter_id == f.fighter_id
        elif f.lock == "CONTEST":
            ct = c.contests[f.lock_ref]
            assert ct.status == "ACTIVE" and f.fighter_id in (ct.a.fighter_id, ct.b.fighter_id)
        elif f.lock == "TOURNAMENT":
            assert c.cups[f.lock_ref].status in ("REGISTRATION", "RUNNING")
        else:
            assert f.lock == "IDLE"
    for o in c.offers.values():
        if o.status == "OPEN":
            assert c.fighters[o.fighter_id].lock_ref == o.offer_id
    for ct in c.contests.values():
        if ct.status == "ACTIVE" and ct.mode != 2:
            for fid in (ct.a.fighter_id, ct.b.fighter_id):
                assert c.fighters[fid].lock == "CONTEST" and c.fighters[fid].lock_ref == ct.contest_id


def traffic(world, ticks, seed=0xF022, check=True):
    rng = random.Random(seed)
    players = [Player(world, f"z{i}") for i in range(8)]
    c = world.contract
    secrets_, absentees = {}, {}
    for _ in range(ticks):
        for p in players:
            if rng.random() > 0.3:
                continue
            f = p.f
            roll = rng.random()
            if roll < 0.2 and f.lock == "IDLE":
                p.enter(expires_in=rng.choice([40, 120, 240]), max_gap=rng.choice([100, 200]))
            elif roll < 0.25 and f.lock == "QUEUED":
                world.send(p.owner, Op.QUEUE_CANCEL, offer_id=f.lock_ref)
            elif roll < 0.3 and f.lock == "IDLE":
                opp = rng.choice(players)
                stake = rng.choice([1000, 2500])
                world.send(p.owner, Op.DUEL_OFFER, stake, fighter_id=p.fid, auth_version=f.auth_version,
                           opponent_id=opp.fid, ruleset_digest=c.m.ruleset.digest, timing_profile_id=1,
                           fee_profile_id=1, stake=stake, format=rng.choice([0, 1, 2]),
                           expires_tick=world.tick + 100)
            elif roll < 0.35:
                for o in list(c.offers.values()):
                    if o.status == "OPEN" and o.kind == "DUEL" and o.opponent_id == p.fid and f.lock == "IDLE":
                        world.send(p.owner, Op.DUEL_ACCEPT, o.amount, offer_id=o.offer_id, fighter_id=p.fid,
                                   auth_version=f.auth_version)
                        break
            elif roll < 0.4:
                world.send(p.owner, Op.WITHDRAW)
            elif roll < 0.42:
                world.raw(p.owner, bytes(rng.getrandbits(8) for _ in range(512)), rng.choice([0, 3]))
            elif roll < 0.43 and f.lock == "IDLE":
                # Sell the fighter to a fresh owner, who registers it.
                buyer = identity(f"buyer{rng.random()}")
                world.owners[p.fid] = buyer
                world.mint(buyer, 100_000)
                if world.send(buyer, Op.REGISTER_FIGHTER, fighter_id=p.fid, registry_version=1).ok:
                    p.owner = p.operator = buyer
                else:
                    world.owners[p.fid] = p.owner
        for fight in list(c.fights.values()):
            if fight.phase == "COMMIT" and fight.start_tick < world.tick <= fight.commit_last:
                for side in (fight.context.participant_a, fight.context.participant_b):
                    slot = fight.slot_of(side.fighter_id)
                    if slot in fight.commits or rng.random() < 0.6:
                        continue
                    absent = absentees.setdefault((fight.fight_id, fight.state.round_index, slot),
                                                  rng.random() < 0.04)
                    if absent:
                        continue            # this fighter never commits this round and faults
                    plan = Plan.of([rng.choice(SUBMITTED) for _ in range(6)])
                    fields, salt = commit_fields(world, fight.fight_id, side.fighter_id, side.operator, plan)
                    world.send(side.operator, Op.COMMIT, **fields)
                    secrets_[(fight.fight_id, fight.state.round_index, slot)] = (plan, salt, side)
            elif fight.phase == "REVEAL":
                for slot in "AB":
                    key = (fight.fight_id, fight.state.round_index, slot)
                    if key in secrets_ and slot not in fight.reveals and rng.random() < 0.5:
                        plan, salt, side = secrets_[key]
                        if rng.random() < 0.03:
                            salt = bytes(32)              # a wrong reveal; may be corrected later
                        r = world.send(side.operator, Op.REVEAL,
                                       **reveal_fields(world, fight.fight_id, side.fighter_id, plan, salt))
                        assert r.code in (Code.OK, Code.BAD_COMMITMENT, Code.DUPLICATE)
        if rng.random() < 0.002:
            world.skip_ticks(rng.randint(1, 3))
        world.end()
        if check:
            world.check_conservation()
            _check_locks(world)


def test_random_traffic_conserves_and_keeps_locks(world):  # noqa: F811
    traffic(world, TICKS)
    c = world.contract
    settled = [ct for ct in c.contests.values() if ct.status == "DONE"]
    assert len(settled) > 20
    kinds = {ct.result["kind"] for ct in settled}
    assert {"COMBAT", "FORFEIT"} <= kinds


def test_journal_replay_rebuilds_the_identical_contract(world, tmp_path):  # noqa: F811
    from qdojo.combat import store
    traffic(world, 1500, seed=7, check=False)
    path = tmp_path / "combat.journal"
    store.write(path, world.manifest, world.journal, world.contract.event_digest)
    head, records = store.load(path)
    rebuilt = store.replay(world.manifest, head, records)
    assert rebuilt.event_digest == world.contract.event_digest
    assert rebuilt.ledger.credits == world.contract.ledger.credits
    assert {k: (f.lock, f.lifetime) for k, f in rebuilt.fighters.items()} == \
        {k: (f.lock, f.lifetime) for k, f in world.contract.fighters.items()}
    # A torn final append is tolerated; a digest mismatch is not.
    with open(path, "a") as f:
        f.write('{"k":"call","t":')
    store.replay(world.manifest, *store.load(path))
    records[-1]["event_digest"] = "00" * 32
    import pytest
    with pytest.raises(store.StoreError):
        store.replay(world.manifest, head, records)
    (tmp_path / "rounds.json").write_text("{}")
    with pytest.raises(store.StoreError):
        store.write(path, world.manifest, [])
