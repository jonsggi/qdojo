import datetime as dt
import json

import pytest

from qdojo.combat import npcs
from qdojo.combat.bot import Bot, BotStop, Budget, BudgetState, decide, policy_chooser
from qdojo.combat.devnet import Devnet
from qdojo.combat.rules import candidate_1

RULES = candidate_1()
NOON = dt.datetime(2026, 9, 23, 12, tzinfo=dt.timezone.utc)


def _bot(net, label, policy, tmp_path, **budget):
    fid, owner = net.ensure_fighter(label)
    b = Budget(ruleset_digest=RULES.digest.hex(), **budget)
    return Bot(net.client(owner), RULES, fid, owner, owner, policy_chooser(RULES, policy, bytes(32)), b,
               tmp_path / label, clock=lambda: NOON)


def _run(net, bots, ticks):
    for _ in range(ticks):
        for b in bots:
            b.step()
        net.world.end()
        net.world.check_conservation()


def test_two_bots_fight_ranked_on_the_devnet(tmp_path):
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", npcs.scout_v1, tmp_path)
    b = _bot(net, "beta", npcs.ROSTER["jabber-v1"].policy, tmp_path)
    _run(net, [a, b], 400)
    c = net.world.contract
    done = [x for x in c.contests.values() if x.status == "DONE"]
    assert done and all(x.result["kind"] == "COMBAT" for x in done)
    # Budgets saw the settlements; the scout outplays the jabber.
    settled = [s for s in a.bstate.spends if s.returned is not None]
    assert settled and sum(s.returned - s.stake for s in settled) > 0
    journal = (tmp_path / "alpha" / "secret-plans.jsonl")
    assert oct(journal.stat().st_mode)[-3:] == "600"


def test_restart_resumes_the_journalled_plan(tmp_path):
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", npcs.mixed_v1, tmp_path)
    b = _bot(net, "beta", npcs.mixed_v1, tmp_path)
    # Run until alpha has committed in round 0.
    for _ in range(100):
        a.step(), b.step()
        net.world.end()
        if a.journal.records:
            break
    rec = next(iter(a.journal.records.values()))
    net.save()
    # A new process: same state dir, a devnet replayed from disk.
    net2 = Devnet(tmp_path / "net")
    a2 = _bot(net2, "alpha", npcs.random_v1, tmp_path)      # a different policy must not matter now
    b2 = _bot(net2, "beta", npcs.mixed_v1, tmp_path)
    assert net2.world.contract.event_digest == net.world.contract.event_digest
    for _ in range(60):
        a2.step(), b2.step()
        net2.world.end()
    fight = net2.world.contract.fights[rec["fight_id"]]
    assert fight.rounds and fight.rounds[0]["plans"][fight.slot_of(a2.fighter_id)].hex() == rec["plan"]


def test_lost_salt_stops_instead_of_substituting(tmp_path):
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", npcs.mixed_v1, tmp_path)
    b = _bot(net, "beta", npcs.mixed_v1, tmp_path)
    for _ in range(100):
        a.step(), b.step()
        net.world.end()
        fid = a.client.fighter(a.fighter_id)["active_fight"]
        if fid and net.world.contract.fights[fid].phase == "REVEAL":
            break
    (tmp_path / "alpha" / "secret-plans.jsonl").unlink()
    a3 = _bot(net, "alpha", npcs.mixed_v1, tmp_path)
    with pytest.raises(BotStop):
        a3.step()


def test_scheduler_denies_on_unknowns_and_limits():
    b = Budget(ruleset_digest="ab", max_total_escrow=1000, max_daily_net_loss=1500, max_fights_per_day=3)
    st = BudgetState()
    assert decide(b, st, "d", 0, 1000, 1, None, "ab") == (False, "wallet balance unreadable")
    assert decide(b, st, "d", 0, 1000, 1, 10**6, "cd")[0] is False
    assert decide(Budget(), st, "d", 0, 1000, 1, 10**6, "ab")[0] is False        # nothing pinned
    assert decide(b, st, "d", 0, 1000, 1, 10**6, "ab") == (True, "ok")
    from qdojo.combat.bot import Spend
    st.spends.append(Spend("d", "offer:1", 1000))
    assert decide(b, st, "d", 0, 1000, 1, 10**6, "ab")[1] == "total escrow limit"
    st.spends[0].returned = 0                                                    # lost it
    assert decide(b, st, "d", 0, 1000, 1, 10**6, "ab")[1] == "daily net-loss limit"
    st.spends[0].returned = 1900                                                 # won: wins never offset committed
    st.spends += [Spend("d", "x", 1000, 1000), Spend("d", "y", 1000, 1000)]
    assert decide(b, st, "d", 0, 1000, 1, 10**6, "ab")[1] == "daily fight limit"
    st.faults = 1
    assert "fault" in decide(b, st, "e", 0, 1000, 1, 10**6, "ab")[1]


def test_bot_stops_after_a_fault(tmp_path):
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", npcs.mixed_v1, tmp_path)
    b = _bot(net, "beta", npcs.mixed_v1, tmp_path)
    # beta goes silent after entering once.
    for _ in range(200):
        a.step()
        if b.bstate.spends == []:
            b.step()
        net.world.end()
    assert b.bstate.spends and a.bstate.faults == 0
    b.step()
    assert b.bstate.faults == 1
    assert b.step().startswith("deny: stopped after 1")


def test_devnet_refuses_legacy_state(tmp_path):
    (tmp_path / "rounds.json").write_text(json.dumps({}))
    from qdojo.combat.store import StoreError
    with pytest.raises(StoreError):
        Devnet(tmp_path)
