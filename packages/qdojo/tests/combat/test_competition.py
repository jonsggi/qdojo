"""competition.md §6 scenarios: tied replays, capacity postponement, seasons."""
from qdojo.combat.codec import Op
from qdojo.combat.contract import development_manifest
from qdojo.combat.rules import candidate_1
from qdojo.combat.sim import World

from .test_contract import ADMIN, DEV, HOUSE, JABS, KO_PLAN, RESTS, SHARE, Player, _cup, _run_cup, play_fight, until_match


def _world(**kw):
    w = World(development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE, **kw))
    w.mint(ADMIN, 10**9)
    return w


def test_all_draw_cup_replays_then_aborts_with_refunds():
    w = _world()
    cup = _cup(w, sponsorship=400)
    players = [Player(w, f"d{i}") for i in range(4)]
    for p in players:
        assert w.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1).ok
    w.run_until(cup.descriptor["registration_close"] + 1)
    _run_cup(w, cup, players, lambda p: RESTS)
    first_level = [p for p in cup.pairings.values() if p.level == 0]
    assert all(p.status == "UNRESOLVED" for p in first_level)
    contests = [c for c in w.contract.contests.values() if c.cup_id == cup.cup_id]
    assert any(c.replay for c in contests) and all(len(c.fights) in (5, 3) for c in contests)
    assert cup.status == "ABORTED"
    assert all(w.contract.ledger.credits[p.owner] == 2000 for p in players)
    assert w.contract.ledger.credits[ADMIN] == 400 and HOUSE not in w.contract.ledger.credits
    w.check_conservation()


def test_capacity_shortfall_postpones_once_then_aborts():
    w = _world(max_fights=2)
    cup = _cup(w)
    players = [Player(w, f"p{i}") for i in range(8)]       # level 0 needs four fight slots
    for p in players:
        w.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1)
    close = cup.descriptor["registration_close"]
    w.run_until(close + 1)
    assert cup.status == "RUNNING" and cup.pending_reservation and 0 in cup.postponed
    assert cup.level_start == close + 120 + 3000
    w.run_until(cup.level_start)
    assert cup.status == "ABORTED"
    assert all(w.contract.ledger.credits[p.owner] == 2000 for p in players)
    assert all(p.f.lock == "IDLE" for p in players)
    w.check_conservation()


def test_cup_winner_takes_prize_through_final_bo5():
    w = _world()
    cup = _cup(w, sponsorship=0)
    players = [Player(w, f"f{i}") for i in range(4)]
    champ, runner = players[2], players[0]
    # Seeds 1 and 2 by rating: they can only meet in the final.
    champ.f.lifetime, runner.f.lifetime = 1300, 1200
    for p in players:
        w.send(p.owner, Op.CUP_REGISTER, 2000, cup_id=cup.cup_id, fighter_id=p.fid, auth_version=1)
    w.run_until(cup.descriptor["registration_close"] + 1)
    _run_cup(w, cup, players, lambda p: JABS if p is champ else KO_PLAN if p is runner else RESTS)
    assert cup.status == "COMPLETE" and cup.champion == champ.fid
    final = [c for c in w.contract.contests.values() if c.cup_id == cup.cup_id][-1]
    assert final.series.need == 3                          # the final is BO5
    assert w.contract.ledger.credits[champ.owner] == 8000 - 400
    w.check_conservation()


def test_season_assignment_follows_start_epoch_and_qualification():
    w = _world(ticks_per_epoch=400, season_start_epoch=1, season_epochs=2)
    m = w.contract.m
    players = [Player(w, f"s{i}") for i in range(6)]
    champion = players[0]
    # Round-robin ranked fights across both epochs of season 1.
    played = 0
    while m.season(w.tick) == 1:
        for opp in players[1:]:
            if m.season(w.tick) != 1:
                break
            w.run_until(max(w.tick, champion.f.cooldown_until, opp.f.cooldown_until) + 121)
            if m.season(w.tick) != 1:
                break
            if not (champion.enter(expires_in=1200).ok and opp.enter(expires_in=1200).ok):
                continue
            fid = until_match(w, champion, opp)
            play_fight(w, fid, champion, KO_PLAN, opp, RESTS)
            played += 1
            for p in (champion, opp):
                if p.f.lock == "QUEUED":
                    w.send(p.owner, Op.QUEUE_CANCEL, offer_id=p.f.lock_ref)
    st = champion.f.season_stats[1]
    assert st["fights"] == played and st["wins"] == played
    assert champion.f.season_rating[1] > 1000 and champion.f.lifetime > 1000
    standings = w.contract.season_standings(1, w.tick)
    assert standings["standings"][0]["fighter_id"] == champion.fid
    # Too few fights for the 12-fight rule in this short season: honestly no champion.
    assert (standings["status"] == "CHAMPION") == (st["fights"] >= 12 and st["final_epoch_fights"] >= 3
                                                  and len(st["defeated"]) >= 3 and champion.f.placement >= 10)
    w.check_conservation()
