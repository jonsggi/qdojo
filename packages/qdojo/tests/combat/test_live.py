import json

from qdojo.combat import live
from qdojo.combat.codec import Code
from qdojo.combat.contract import CallResult
from qdojo.combat.sim import identity


def test_live_run_exports_pruned_data_and_resumes(tmp_path):
    out = tmp_path / "web" / "combat" / "v1"
    lineup = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"},
              {"label": "c", "policy": "mixed-v1"}]
    live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=40, keep=3, ticks=500, log=lambda m: None)
    index = json.loads((out / "index.json").read_text())
    assert index["deployment"]["kind"] == "devnet" and index["deployment"]["currency"] == "devnet QU"
    kept = {p.name.split(".")[0] for p in (out / "fights").iterdir()}
    assert kept == set(index["fights"]) | set(index["active_fights"]) and len(index["fights"]) <= 3
    first_tick = int(index["generated_tick"])
    live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=40, keep=3, ticks=40, log=lambda m: None)
    assert int(json.loads((out / "index.json").read_text())["generated_tick"]) == first_tick + 40
    # Finished fights are written once; a later export does not rewrite them.
    index = json.loads((out / "index.json").read_text())
    done = [f for f in index["fights"] if f not in index["active_fights"] and (out / "fights" / f"{f}.json").exists()]
    if done:
        p = out / "fights" / f"{done[0]}.json"
        before = p.stat().st_mtime_ns
        live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=40, keep=3, ticks=40, log=lambda m: None)
        if p.exists():
            assert p.stat().st_mtime_ns == before


def test_a_fight_exported_while_live_is_rewritten_when_it_ends(tmp_path):
    # Regression: a finished fight's file was skipped whenever it existed, so a
    # file first written mid-fight stayed frozen in its live state forever.
    out = tmp_path / "web" / "combat" / "v1"
    lineup = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"}]
    live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=5, keep=50, ticks=600, log=lambda m: None)
    index = json.loads((out / "index.json").read_text())
    done = [f for f in index["fights"] if f not in index["active_fights"]]
    assert done, "the run should finish at least one fight"
    for f in done:
        doc = json.loads((out / "fights" / f"{f}.json").read_text())
        assert doc["final"] is True and doc["phase"] == "DONE" and doc["result"], f
    fighter = json.loads((out / "fighters" / f"{index['fighters'][0]}.json").read_text())
    total = sum(sum(r.values()) for r in fighter["records_by_mode"].values())
    assert total >= 1 and set(fighter["records_by_mode"]) <= {"ranked", "duel", "cup", "npc", "training"}


def test_a_collector_running_fighters_takes_over_another_it_buys_within_a_few_ticks(tmp_path):
    """Regression (2026-10-11): the new owner's RegisterFighter went out on a
    nonce count the arena kept itself, which the collector's bots for the
    fighters it already held had long passed: refused STALE once a tick, for
    up to 1,200 ticks, the fighter idle meanwhile. It is now the collector's
    own transaction through the chain."""
    logs = []
    lineup = [{"label": label, "policy": policy} for label, policy in
              (("a", "scout-v1"), ("b", "kicker-v1"), ("c", "mixed-v1"), ("d", "mixed-v1"))]
    arena = live.Arena(tmp_path / "net", lineup, seed=3, deterministic=True, market_every=0, log=logs.append)
    first, second = list(arena.labels)[:2]
    collector = identity("test-collector")
    arena.w.mint(collector, 10**12)

    def buy(fid):
        for _ in range(600):                          # a fighter changes hands only while idle
            if arena.nfts.poll(arena.nfts.transfer(arena.nfts.owner(fid), fid, collector,
                                                   immediate=True))["code"] == "OK":
                return
            arena.step()
        raise AssertionError("the fighter never came free")

    def takes_over(fid):
        for _ in range(12):                           # latency 1-3 ticks, a dropped send or two
            arena.step()
            if arena.bots[fid].wallet == collector:
                return True
        return False

    buy(first)
    assert takes_over(first)
    for _ in range(4000):                             # the collector's bot plays: its nonces run on
        arena.step()
        if arena.w.contract.nonces.get(collector, (0,))[0] > 40:
            break
    assert arena.w.contract.nonces[collector][0] > 40
    buy(second)
    assert takes_over(second)
    assert arena.w.contract.fighters[second].owner == collector
    assert not [m for m in logs if "registration refused" in m]


def test_a_refused_or_dropped_registration_is_sent_again_and_logged_once_per_reason(tmp_path):
    logs = []
    arena = live.Arena(tmp_path / "net", [{"label": "a", "policy": "mixed-v1"}], seed=3, deterministic=True,
                       market_every=0, log=logs.append)
    fid, owner = next(iter(arena.labels)), identity("test-collector")
    outcomes = iter([CallResult(Code.NOT_OWNER), "dropped", CallResult(Code.NOT_OWNER), None])

    class Chain:                                  # what _register_for asks of the chain, scripted
        sent = 0

        def send(self, who, op, **fields):
            assert who == owner
            self.sent += 1
            return self.sent

        def poll(self, receipt):
            return next(outcomes)
    arena.chain = chain = Chain()
    for _ in range(5):
        arena._register_for(fid, owner)
    assert chain.sent == 4                        # the first, refused, dropped, refused again; then one in flight
    assert [m.split(": ", 1)[1] for m in logs if "registration" in m] == [
        "a: new owner's registration refused (NOT_OWNER); sending it again",
        "a: new owner's registration dropped; sending it again"]


def test_a_restart_while_a_new_owners_registration_is_in_flight_sends_it_again(tmp_path):
    """Only an included transaction is in the journal: after a restart the
    new owner's bot runs (it follows the NFT), and the registration it needs
    is read from the contract and sent again, not taken as done."""
    lineup = [{"label": "a", "policy": "mixed-v1"}, {"label": "b", "policy": "mixed-v1"}]
    kw = dict(seed=3, deterministic=True, market_every=0, drop_rate=0.0, log=lambda m: None)
    arena = live.Arena(tmp_path / "net", lineup, **kw)
    fid, collector = next(iter(arena.labels)), identity("test-collector")
    arena.w.mint(collector, 10**12)
    assert arena.nfts.poll(arena.nfts.transfer(arena.nfts.owner(fid), fid, collector, immediate=True))["code"] == "OK"
    arena.step()
    assert arena.chain.poll(arena._registering[fid][1]) is None       # in flight
    arena.save()
    again = live.Arena(tmp_path / "net", lineup, **kw)
    assert again.bots[fid].wallet == collector and again.w.contract.fighters[fid].owner != collector
    for _ in range(4):
        again.step()
    assert again.w.contract.fighters[fid].owner == collector


def test_the_arena_proposes_no_duel_its_target_would_decline(tmp_path):
    """The target's own filters are asked first: an offer it would decline
    only held the challenger's stake until it expired."""
    logs = []
    lineup = [{"label": label, "policy": "mixed-v1", "duels": True, "ranked": False} for label in ("a", "b", "c")]
    arena = live.Arena(tmp_path / "net", lineup, seed=3, deterministic=True, market_every=0, duel_every=1,
                       cup_every=10**9, log=logs.append)
    a, b, c = list(arena.labels)
    for target in (b, c):                         # b and c each lost all of three series to a
        arena.bots[target].bstate.duel_h2h[a.hex()] = [0, 0, 3]
    assert arena.bots[b].declines_duel(a, 1000, 1, 1000) == "lost 3 of 3 series to this challenger"
    for _ in range(300):
        arena.step()
    proposed = [m.split(": ", 1)[1] for m in logs if "duel challenge" in m]
    assert proposed and not [m for m in proposed if m.startswith("duel challenge a ->")]
    assert not [m for m in logs if "declined: lost" in m]
