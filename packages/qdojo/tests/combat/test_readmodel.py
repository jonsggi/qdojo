"""The read model: rebuilt from scratch equals followed incrementally (AUD-026)."""
import json

import pytest

from qdojo.combat import export, live
from qdojo.combat import readmodel as rm

LINEUP = [{"label": "a", "policy": "scout-v1", "cups": True, "founding": True},
          {"label": "b", "policy": "kicker-v1", "cups": True},
          {"label": "e", "policy": "reader-v1", "cups": True}, {"label": "f", "policy": "search-v1", "cups": True},
          {"label": "c", "policy": "mixed-v1", "duels": True, "ranked": False},
          {"label": "d", "policy": "jabber-v1", "duels": True, "ranked": False}]


def _arena(tmp_path, **kw):
    return live.Arena(tmp_path / "arena", LINEUP, seed=11, deterministic=True, cup_every=500, duel_every=90,
                      market_every=0, log=lambda m: None, **kw)


def _export(arena, out):
    export.export_all(arena.w.contract, out, keep=5, deployment=arena.deployment(1.5))


def test_incremental_equals_rebuild_and_survives_a_restart(tmp_path):
    arena = _arena(tmp_path)
    out = tmp_path / "web" / "combat" / "v1"
    db = tmp_path / "inc.sqlite"
    fl = None
    sold = False
    # Irregular sync points, a restart from the snapshot half way, and an
    # export (names, owners) that changes between syncs.
    for i in range(1, 1601):
        arena.step()
        if i >= 700 and not sold:             # one NFT sale, whenever a fighter is idle
            n, arena.market_every = arena.state["collectors"], 1
            arena._maybe_market()
            arena.market_every, sold = 0, arena.state["collectors"] > n
        if i % 37 == 0 or i % 101 == 0:
            arena.save()
            if i % 3 == 0:
                _export(arena, out)
            if fl is None:
                fl = rm.Follower(arena.dir, db, out, log=lambda m: None)
            fl.step()
        if i == 800:
            fl.save_snapshot()
            fl.conn.close()
            fl = rm.Follower(arena.dir, db, out, log=lambda m: None)
            assert fl.offset > 0, "the restart resumed from the snapshot, not byte 0"
    arena.save()
    _export(arena, out)
    fl.step()
    assert fl.replica.contract.event_digest == arena.w.contract.event_digest
    stats = rm.rebuild(arena.dir, tmp_path / "full.sqlite", out, log=lambda m: None)
    assert stats["fights"] == len(arena.w.contract.fights) > 10
    inc, full = rm.dump(fl.conn), rm.dump(rm.connect(tmp_path / "full.sqlite", readonly=True))
    for table in rm.TABLES:
        assert inc[table] == full[table], table
    # Every fight is kept (the static export keeps 5); duels, cups, ratings and a sale are there.
    assert len(full["fights"]) == len(arena.w.contract.fights)
    modes = {r[2] for r in full["fights"]}
    assert {"ranked", "duel", "cup"} <= modes
    assert full["ratings"] and full["cups"] and full["seasons"]
    assert any(r[1] > 0 for r in full["ownership"]), "the market sold a fighter"
    assert {r[2] for r in full["fighters"]} == {"house"}


def test_torn_tail_waits_for_the_rest_of_the_line(tmp_path):
    arena = _arena(tmp_path)
    for _ in range(50):
        arena.step()
    arena.save()
    fl = rm.Follower(arena.dir, tmp_path / "rm.sqlite", snapshot=False, log=lambda m: None)
    fl.step()
    tick = fl.replica.tick
    line = json.dumps({"k": "end", "t": tick}, separators=(",", ":")) + "\n"
    journal = arena.dir / rm.JOURNAL
    with open(journal, "a") as f:
        f.write(line[:7])                     # a writer mid-append
    assert fl.poll() == 0 and fl.replica.tick == tick
    with open(journal, "a") as f:
        f.write(line[7:])
    assert fl.poll() == 1 and fl.replica.tick == tick + 1


def test_a_replaced_journal_is_replayed_from_the_start(tmp_path):
    arena = _arena(tmp_path)
    for _ in range(60):
        arena.step()
    arena.save()
    fl = rm.Follower(arena.dir, tmp_path / "rm.sqlite", snapshot=False, log=lambda m: None)
    fl.step()
    journal = arena.dir / rm.JOURNAL
    lines = journal.read_text().splitlines(keepends=True)
    journal.write_text("".join(lines[:len(lines) // 2]))          # shorter: a different journal
    fl.step()
    assert fl.offset == journal.stat().st_size
    assert rm.get_meta(fl.conn, "journal_offset") == fl.offset         # re-indexed, not stuck behind the old one
    # A follower started later on the same database also notices, from the stored signature.
    fl.conn.close()
    journal.write_text("".join(lines[:len(lines) // 3]))
    fl2 = rm.Follower(arena.dir, tmp_path / "rm.sqlite", snapshot=False, log=lambda m: None)
    fl2.step()
    assert rm.get_meta(fl2.conn, "journal_offset") == journal.stat().st_size


def test_a_foreign_snapshot_is_ignored(tmp_path):
    arena = _arena(tmp_path)
    for _ in range(40):
        arena.step()
    arena.save()
    db = tmp_path / "rm.sqlite"
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    fl.step()
    fl.save_snapshot()
    snap = db.with_suffix(".replica")
    snap.chmod(0o644)                         # not private: never unpickled
    fl2 = rm.Follower(arena.dir, db, log=lambda m: None)
    assert fl2.offset == 0


def test_outcomes_from_each_side():
    assert rm.outcome_of({"kind": "COMBAT", "winner": "A"}, "A") == "W"
    assert rm.outcome_of({"kind": "COMBAT", "winner": None}, "B") == "D"
    assert rm.outcome_of({"kind": "FORFEIT", "winner": "B"}, "A") == "FL"
    assert rm.outcome_of({"kind": "VOID", "winner": None}, "A") == "N"
    assert rm.outcome_of(None, "A") is None


@pytest.mark.parametrize("meta,npc,want", [({"origin": "outside"}, False, "outside"), ({"name": "x"}, False, "house"),
                                           ({}, True, "house"), ({}, False, "unknown")])
def test_origin(meta, npc, want):
    assert rm.origin_of(meta, npc) == want
