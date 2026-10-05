"""Aggregate builder participation (AUD-039): counts from public chain and arena data only."""
import json
import re

import pytest

from qdojo.combat import community
from qdojo.combat import evaluate as E
from qdojo.combat import readmodel as rm
from qdojo.combat.bot import Bot, Budget, policy_chooser
from qdojo.combat.codec import Op
from qdojo.combat.rules import candidate_1

from .test_join import J, LIMITS, Rig

HEX = re.compile(r"[0-9a-f]{64}")


def _fights_of(c, fid):
    return [f for f in c.fights.values() if fid in (f.context.participant_a.fighter_id, f.context.participant_b.fighter_id)]


def test_outside_participation_is_counted_and_rebuild_equals_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "RUN_GAP_TICKS", 60)
    rig = Rig(tmp_path)
    try:
        subseed, pub, body = rig.register("Outsider", tmp_path / "me.seed")
        rig.http.post("/api/v1/join/register", body)
        rig.tick()
        fid = bytes.fromhex(rig.http.get(f"/api/v1/join/status?owner={pub.hex()}")["fighter_id"])
        client = J.RemoteClient(rig.http, rig.info, subseed, pub, fid, tmp_path / "state")
        client.refresh()
        receipt = client.send(Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        for _ in range(6):
            rig.tick()
            client.refresh()
            if client.poll(receipt) is not None:
                break
        rules = candidate_1()

        def run_bot(state, until_fights):
            bot = Bot(client, rules, fid, pub, pub, policy_chooser(rules, E.policy_by_name("mixed-v1"), b"\1" * 32),
                      Budget(ruleset_digest=rules.digest.hex(), max_stake=5000, max_total_escrow=20000), state)
            for _ in range(400):
                client.refresh()
                bot.step()
                rig.tick()
                done = [f for f in _fights_of(rig.arena.w.contract, fid) if f.phase == "DONE"]
                if len(done) >= until_fights:
                    break
            # Let the last commit/reveal settle so the bot is idle when stopped.
            for _ in range(30):
                client.refresh()
                bot.step()
                rig.tick()

        run_bot(tmp_path / "state", 1)
        rig.tick(80)                                   # the builder stops the bot for longer than the gap
        run_bot(tmp_path / "state", 1)                 # ... and starts it again (a second bot run)
        rig.export()
        rig.fl.step()

        doc = rig.http.get("/api/v1/community")
        assert doc["schema"] == "qdojo.combat.api.community.v1"
        assert doc["fighters"] == {"house": 2, "outside": 1, "operator_tests": 0}
        assert doc["outside"]["builders"] == 1 and doc["outside"]["transactions"] > 3
        assert doc["active_builders"]["today"] == 1 and doc["active_builders"]["last_7_days"] == 1
        assert doc["bot_runs"]["total"] == 2 and doc["bot_runs"]["builders_with_two_or_more"] == 1
        done = [f for f in _fights_of(rig.arena.w.contract, fid) if f.phase == "DONE"]
        assert doc["fights"]["total"]["outside_vs_house"] == len(done) >= 1
        assert doc["fights"]["total"]["outside_vs_outside"] == 0
        all_done = sum(1 for f in rig.arena.w.contract.fights.values() if f.phase == "DONE")
        assert sum(doc["fights"]["total"].values()) == all_done
        # Aggregates only: no identity, fighter ID or name in the document.
        raw = json.dumps(doc)
        assert not HEX.search(raw) and "Outsider" not in raw
        # The house bots' own transactions never count as builder activity.
        house_who = {r[0] for r in rig.fl.conn.execute("SELECT DISTINCT who FROM activity")} - {pub.hex()}
        assert house_who, "house bots are in the activity table too"

        # Incremental (the follower, synced at every tick) equals a rebuild from the journal.
        rig.arena.save()
        rig.fl.step()
        rm.rebuild(rig.dir, tmp_path / "full.sqlite", rig.out, log=lambda m: None)
        inc, full = rm.dump(rig.fl.conn), rm.dump(rm.connect(tmp_path / "full.sqlite", readonly=True))
        for table in rm.TABLES:
            assert inc[table] == full[table], table
        assert len([r for r in full["bot_runs"] if r[0] == pub.hex()]) == 2
        assert community.measure(rm.connect(tmp_path / "full.sqlite", readonly=True)) == \
            {k: v for k, v in doc.items() if k not in ("schema", "generated_tick")}
    finally:
        rig.srv.shutdown()


def _synthetic(tmp_path, tick, rows):
    """A read-model database with hand-made rows (day = 10 ticks: tick_seconds 8640)."""
    conn = rm.connect(tmp_path / "rm.sqlite")
    rm.set_meta(conn, "tick", tick)
    rm.set_meta(conn, "deployment", {"tick_seconds": 8640})
    for t, vals in rows:
        conn.execute(f"INSERT INTO {t} VALUES({','.join('?' * len(vals))})", vals)
    conn.commit()
    return conn


def _fighter(fid, origin, owner, name=None):
    return ("fighters", (fid, name, origin, None, 0, owner, owner, 0, "", 1000, 0, 1, None, "{}", "{}", "{}", 0, 0, None))


def test_days_weeks_and_retention(tmp_path):
    h, o1, o2, o3 = ("h" * 64, "1" * 64, "2" * 64, "3" * 64)
    k1, k2 = ("a" * 64, "b" * 64)
    rows = [_fighter(h, "house", "c" * 64), _fighter(o1, "outside", k1), _fighter(o2, "outside", k1),
            _fighter(o3, "outside", k2), _fighter("t" * 64, "outside", "d" * 64, name="Test-smoke"),
            ("activity", ("d" * 64, 16, 4, 160, 161)), ("bot_runs", ("d" * 64, 0, 160)),
            ("ownership", (o1, 0, 5, None, k1)), ("ownership", (o2, 0, 95, None, k1)), ("ownership", (o3, 0, 150, None, k2)),
            # k1: active on day 0 and day 8 (a new bot run on day 8); k2: day 15 and 16
            ("activity", (k1, 0, 3, 5, 9)), ("activity", (k1, 8, 2, 80, 84)), ("activity", (k2, 15, 1, 150, 150)),
            ("activity", (k2, 16, 1, 165, 165)), ("activity", ("c" * 64, 16, 9, 160, 169)),
            ("bot_runs", (k1, 0, 5)), ("bot_runs", (k1, 1, 80)), ("bot_runs", (k2, 0, 150)),
            ("bot_runs", ("c" * 64, 0, 1))]
    for i, (a, b, end) in enumerate([(o1, h, 7), (o1, o3, 155), (h, h, 166), (o3, h, 168)]):
        rows.append(("fights", (i + 1, i + 1, "ranked", a, b, "DONE", 1, end - 3, end, "COMBAT", a, "KO", 3, b"", None)))
    rows.append(("fights", (8, 8, "ranked", "t" * 64, o1, "DONE", 1, 160, 162, "COMBAT", o1, "KO", 3, b"", None)))
    rows.append(("fights", (9, 9, "ranked", h, o1, "LIVE", 0, 160, None, None, None, None, 1, b"", None)))
    d = community.measure(_synthetic(tmp_path, 169, rows))
    assert d["basis"]["day_ticks"] == 10 and d["basis"]["today"] == 16
    assert d["fighters"] == {"house": 1, "outside": 3, "operator_tests": 1}     # test-... is the operator's
    assert d["outside"]["builders"] == 2
    assert d["outside"]["registered_by_day"] == [{"day": 0, "fighters": 1}, {"day": 9, "fighters": 1},
                                                 {"day": 15, "fighters": 1}]
    assert d["outside"]["transactions"] == 7                      # the house identity's 9 calls are not counted
    assert d["active_builders"]["today"] == 1 and d["active_builders"]["last_7_days"] == 1
    assert d["active_builders"]["ever"] == 2
    assert {x["day"]: x["builders"] for x in d["active_builders"]["by_day"]}[8] == 1
    assert d["fights"]["total"] == {"house_vs_house": 1, "outside_vs_house": 3, "outside_vs_outside": 1}
    assert d["fights"]["today"] == {"house_vs_house": 1, "outside_vs_house": 2, "outside_vs_outside": 0}
    assert d["fights"]["last_7_days"]["outside_vs_outside"] == 1
    assert d["bot_runs"] == {"total": 3, "builders_with_two_or_more": 1, "last_7_days": 1}
    # k1 started on day 0: eligible (day 13 is over), active and restarted on day 8; k2 is too new.
    assert d["retention"] == {"week_2_active": {"eligible": 1, "retained": 1},
                              "week_2_new_run": {"eligible": 1, "retained": 1}}


def test_an_arena_without_outside_builders(tmp_path):
    rows = [_fighter("h" * 64, "house", "c" * 64),
            ("fights", (1, 1, "ranked", "h" * 64, "h" * 64, "DONE", 1, 1, 4, "COMBAT", None, "HP_TIE", 3, b"", None))]
    d = community.measure(_synthetic(tmp_path, 9, rows))
    assert d["outside"]["builders"] == 0 and d["active_builders"]["ever"] == 0
    assert d["fights"]["total"]["house_vs_house"] == 1
    assert d["retention"]["week_2_active"] == {"eligible": 0, "retained": 0}


@pytest.mark.parametrize("ts", [None, "x", 0])
def test_tick_seconds_falls_back(tmp_path, ts):
    conn = rm.connect(tmp_path / "rm.sqlite")
    rm.set_meta(conn, "tick", 1)
    rm.set_meta(conn, "deployment", {"tick_seconds": ts})
    conn.commit()
    assert community.measure(conn)["basis"]["day_ticks"] == 57_600


def test_limits_fixture_is_the_beta_recommendation():
    """deploy/systemd/join-limits.beta.json (docs/beta.md §4) loads as join.Limits."""
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "deploy" / "systemd" / "join-limits.beta.json"
    lim = J.Limits.load(path)
    assert lim.max_outside_fighters == 16 and lim.registrations_per_ip_day == 2
    assert lim.grant_qu >= 20 * lim.max_amount, "the grant covers at least twenty top-tier stakes"
    assert LIMITS.max_outside_fighters == 2      # the test rig's own limits are unrelated
