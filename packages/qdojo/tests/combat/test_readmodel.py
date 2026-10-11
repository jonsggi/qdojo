"""The read model: rebuilt from scratch equals followed incrementally (AUD-026)."""
import inspect
import json
import pickle
import sqlite3
import threading
from pathlib import Path

import pytest

from qdojo.combat import export, live, store, titles
from qdojo.combat import readmodel as rm
from qdojo.combat.contract import CombatContract

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


def _compact_like(monkeypatch, every, **keep):
    """The arena and the replica compact on the same ticks with the same
    retention, as in production, but often and keeping little: in a short
    run, records leave hot state long before a sync sees them."""
    monkeypatch.setattr(live, "COMPACT_EVERY", every)
    monkeypatch.setattr(titles, "CHECKPOINT_EVERY", every)
    monkeypatch.setattr(live, "compact", lambda c: store.compact(c, **keep))
    monkeypatch.setattr(rm, "compact", lambda c: store.compact(c, **keep, keep_epochs=rm.KEEP_ALL,
                                                               keep_seasons=rm.KEEP_ALL))


SMALL = dict(keep_ticks=50, keep_recent=4, per_fighter=1, keep_cups=1)


def _archived(fl):
    return sum(len(v) for v in fl.replica.archive.values())


def _meta(conn):
    return {k: v for k, v in conn.execute("SELECT key, value FROM meta") if k != "synced_at"}


def _same(conn, db_path):
    """`conn` holds exactly the rows and meta of the database at `db_path`."""
    other = rm.connect(db_path, readonly=True)
    try:
        a, b = rm.dump(conn), rm.dump(other)
        for table in rm.TABLES:
            assert a[table] == b[table], table
        assert _meta(conn) == _meta(other)
    finally:
        other.close()
    return b


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
        if i >= 700 and not sold:             # NFT orders every tick until a sale settles (the chain has latency)
            arena.market_every = 1
            arena._maybe_market()
            arena.market_every, sold = 0, bool(arena.market.sales)
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
    # Every fight ever: the arena compacts finished history out of its own memory.
    assert stats["fights"] == arena.w.contract.next_id["fight"] - 1 > 10
    inc, full = rm.dump(fl.conn), rm.dump(rm.connect(tmp_path / "full.sqlite", readonly=True))
    for table in rm.TABLES:
        assert inc[table] == full[table], table
    # Every fight is kept (the static export keeps 5); duels, cups, ratings and a sale are there.
    assert len(full["fights"]) == arena.w.contract.next_id["fight"] - 1
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


def test_a_snapshot_is_stamped_with_the_code_the_process_runs(tmp_path, monkeypatch):
    """A process stopped after a `git pull` saves its snapshot with the new files
    on disk; the stamp must still be its own code's, or the new process loads an
    old-code replica (2026-10-05)."""
    arena = _arena(tmp_path)
    for _ in range(40):
        arena.step()
    arena.save()
    db = tmp_path / "rm.sqlite"
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    fl.step()
    monkeypatch.setattr(rm, "_hash_code", lambda: "the files on disk changed")
    fl.save_snapshot()
    snap = db.with_suffix(".replica")
    with open(snap, "rb") as f:
        assert rm.snapshot_head(f)["code"] == rm._CODE_VERSION
    # and a snapshot from other code is replayed from the start, refused after
    # its head line, unread (a replica from before head lines was 67 MB)
    monkeypatch.setattr(rm, "_CODE_VERSION", "newer code")
    monkeypatch.setattr(pickle, "load", lambda f: pytest.fail("unpickled a snapshot it cannot use"))
    fl.conn.close()
    assert rm.Follower(arena.dir, db, log=lambda m: None).offset == 0
    snap.write_bytes(pickle.dumps({"code": "newer code", "offset": 1, "replica": None}))
    assert rm.Follower(arena.dir, db, log=lambda m: None).offset == 0


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


def test_the_read_model_follows_a_compacting_snapshotting_arena_with_a_priced_market(tmp_path, monkeypatch):
    """The arena's journal now carries digest checkpoints and NFT operations
    ("nft": mints, asks, escrowed bids, sales), and the arena prunes finished
    history from its own memory. The read model replays its own copy,
    compacted the same way: it must still index every fight, the per-mode
    records, the full ownership history and every market sale, and
    incremental must equal rebuild."""
    from qdojo.combat import devnet
    _compact_like(monkeypatch, 150, keep_ticks=200, keep_recent=10, keep_cups=1)
    monkeypatch.setattr(export, "INDEX_HISTORY", 1)     # index.json keeps one entry: history from fighter files
    arena = live.Arena(tmp_path / "arena", LINEUP, seed=12, deterministic=True, cup_every=500, duel_every=90,
                       market_every=200, log=lambda m: None, snapshot_every=300)
    out = tmp_path / "web" / "combat" / "v1"
    db = tmp_path / "inc.sqlite"
    fl = None
    for i in range(1, 2801):
        arena.step()
        if i % 43 == 0:
            arena.save()
            export.export_all(arena.w.contract, out, keep=5, deployment=arena.deployment(1.5),
                              qualification=arena.qualification, extras=arena.extras())
            fl = fl or rm.Follower(arena.dir, db, out, log=lambda m: None)
            fl.step()
        if i == 1500:                                    # the API restarts from its own snapshot
            fl.save_snapshot()
            fl.conn.close()
            fl = rm.Follower(arena.dir, db, out, log=lambda m: None)
    arena.save()
    export.export_all(arena.w.contract, out, keep=5, deployment=arena.deployment(1.5),
                      qualification=arena.qualification, extras=arena.extras())
    fl.step()
    kinds = {json.loads(x)["k"] for x in (arena.dir / devnet.JOURNAL).read_text().splitlines()}
    assert {"digest", "nft"} <= kinds, "the journal has the new record kinds (market trades are nft records)"
    c = arena.w.contract
    assert c.history.pruned["fights"] > 0 and len(c.fights) < c.next_id["fight"] - 1, "the arena compacted"
    r = fl.replica.contract
    assert r.history.pruned == c.history.pruned and set(r.fights) == set(c.fights), "and the replica alike"
    assert r.event_digest == c.event_digest
    rm.rebuild(arena.dir, tmp_path / "full.sqlite", out, log=lambda m: None)
    inc, full = rm.dump(fl.conn), rm.dump(rm.connect(tmp_path / "full.sqlite", readonly=True))
    for table in rm.TABLES:
        assert inc[table] == full[table], table
    # Full history: every fight, and records by mode equal the arena's (history included).
    assert len(full["fights"]) == c.next_id["fight"] - 1
    conn = rm.connect(tmp_path / "full.sqlite", readonly=True)
    records: dict = {}
    for fid, mode, outcome in conn.execute("SELECT fighter_id, mode, outcome FROM fight_sides"):
        if outcome is None:
            continue
        r = records.setdefault(bytes.fromhex(fid), {}).setdefault(mode, {"W": 0, "D": 0, "L": 0, "FW": 0, "FL": 0,
                                                                         "N": 0})
        r[{"DF": "N", "VOID": "N"}.get(outcome, outcome)] += 1
    assert records == export.records_by_mode(c)
    # Every market sale, with its price, and the full ownership history.
    assert arena.market.sales and len(full["sales"]) == len(arena.market.sales)
    assert [r[5] for r in full["sales"]] == [x["price"] for x in arena.market.sales]
    led = arena.w.nft
    transfers = sum(len(led.ownership(f)) for f in led.tokens)
    assert transfers > len(led.tokens), "at least one fighter changed hands"
    # The NFT tables mirror the ledger the journal rebuilt.
    assert len(full["nft_tokens"]) == len(led.tokens) and len(full["nft_events"]) == len(led.events)
    assert len(full["ownership"]) == transfers
    seasons = [json.loads(r[4]) for r in full["seasons"]]
    assert seasons and all(d["qualification"]["opponents"] <= 4 for d in seasons)
    field = seasons[0]["qualification"]["field"]
    assert seasons[0]["qualification"]["opponents"] == max(2, min(4, round(field * 0.2)))
    # The seasons use the demo profile's qualification rule, like seasons.json.
    econ = rm.get_meta(conn, "economics")
    assert econ["tiers"]["1"]["stake"] == "5000"


# ---- a compacting replica (linear replay) ------------------------------------------

def test_the_replica_compacts_exactly_like_the_arena(monkeypatch):
    """Same ticks, same retention for fights, contests, offers and cups: a
    call naming a record compaction removed gets another answer (next
    test). Only fault counts and season stats, which the contract never
    reads again, stay whole for the database."""
    assert titles.CHECKPOINT_EVERY == live.COMPACT_EVERY
    real, calls = store.compact, []

    def recording(*args, **kw):
        bound = inspect.signature(real).bind(*args, **kw)
        bound.apply_defaults()
        calls.append(dict(bound.arguments))
    monkeypatch.setattr(store, "compact", recording)
    live.compact("contract")
    rm.compact("contract")
    arena, replica = calls
    assert replica.pop("keep_epochs") == replica.pop("keep_seasons") == rm.KEEP_ALL
    del arena["keep_epochs"], arena["keep_seasons"]
    assert replica == arena


def test_the_replica_agrees_with_the_arena_on_a_call_naming_a_compacted_record():
    """Cancelling an offer the arena compacted away is NOT_FOUND there, and no
    nonce is recorded. A replica that never compacted answered DUPLICATE and
    recorded the nonce, so a later call reusing it went another way and the
    replica stopped at the next digest checkpoint ("replica diverged")."""
    from qdojo.combat.codec import Code, Op
    from qdojo.combat.contract import development_manifest
    from qdojo.combat.rules import candidate_1
    from qdojo.combat.sim import World, identity
    admin, fid, owner = identity("admin"), identity("fighter:a"), identity("owner:a")
    m = development_manifest(candidate_1(), admin, identity("house"), identity("dev"), identity("share"))
    w = World(m)
    w.mint(admin, 10**9)
    w.owners[fid] = owner
    w.mint(owner, 10**7)
    assert w.send(admin, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0).ok
    assert w.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok

    def enter(nonce=None):
        return w.send(owner, Op.QUEUE_ENTER, 1000, nonce=nonce, fighter_id=fid,
                      auth_version=w.contract.fighters[fid].auth_version, ruleset_digest=m.ruleset.digest,
                      timing_profile_id=1, fee_profile_id=1, tier_id=1, max_gap=200, expires_tick=w.tick + 240)
    oid = enter().data["offer_id"]
    assert w.send(owner, Op.QUEUE_CANCEL, offer_id=oid).ok
    while w.tick < 3001:                     # the arena: END_TICK, then live.compact on its ticks
        w.end()
        if w.tick % live.COMPACT_EVERY == 0:
            live.compact(w.contract)
    assert oid not in w.contract.offers
    assert w.send(owner, Op.QUEUE_CANCEL, nonce=50, offer_id=oid).code == Code.NOT_FOUND
    assert enter(nonce=50).ok
    w.end()
    rep = rm.Replica(m)
    for rec in json.loads(json.dumps(w.journal)):
        rep.apply(rec)
    rep.apply({"k": "digest", "t": w.tick, "event_seq": w.contract.event_seq,
               "event_digest": w.contract.event_digest.hex()})


def test_every_record_reaches_the_database_though_the_replica_compacts(tmp_path, monkeypatch):
    _compact_like(monkeypatch, 100, **SMALL)
    arena = _arena(tmp_path)
    out = tmp_path / "web" / "combat" / "v1"
    db = tmp_path / "inc.sqlite"
    fl, carried, sold, behind = None, 0, False, 0
    for i in range(1, 2401):
        arena.step()
        if i >= 700 and not sold:             # NFT orders every tick until a sale settles
            arena.market_every = 1
            arena._maybe_market()
            arena.market_every, sold = 0, bool(arena.market.sales)
        # Irregular syncs and a long gap: records finish and leave the
        # replica's hot state before any sync sees them.
        if (i % 37 == 0 or i % 101 == 0) and not 900 < i < 1500:
            arena.save()
            if i % 3 == 0:
                _export(arena, out)
            fl = fl or rm.Follower(arena.dir, db, out, log=lambda m: None)
            while fl.poll():
                pass
            carried = max(carried, _archived(fl))
            assert fl.sync() and _archived(fl) == 0, "a sync takes everything the replica moved out"
        if i == 1600:                          # the API restarts from its own snapshot
            fl.save_snapshot()
            fl.conn.close()
            fl = rm.Follower(arena.dir, db, out, log=lambda m: None)
            assert fl.offset > 0
        if i == 2000:                          # a deploy: other code replays the whole journal, behind the database
            fl.conn.close()
            monkeypatch.setattr(rm, "_CODE_VERSION", "the next deploy")
            fl = rm.Follower(arena.dir, db, out, log=lambda m: None)
            assert fl.offset == 0 < fl.db_offset
            while fl.poll(16 << 10):
                behind += 1
                assert _archived(fl) == 0, "behind the database the archive holds nothing"
    arena.save()
    _export(arena, out)
    fl.step()
    c = fl.replica.contract
    assert c.event_digest == arena.w.contract.event_digest
    assert c.history.pruned["fights"] > 0 and len(c.fights) < c.next_id["fight"] - 1, "the replica compacted"
    assert carried > 0 and behind > 10
    stats = rm.rebuild(arena.dir, tmp_path / "full.sqlite", out, log=lambda m: None)
    assert stats["fights"] == c.next_id["fight"] - 1
    full = _same(fl.conn, tmp_path / "full.sqlite")
    assert len(full["fights"]) == c.next_id["fight"] - 1 and full["sales"] and full["cups"]
    # A snapshot never resumes over a database that lacks what its replica dropped.
    fl.save_snapshot()
    fl.conn.close()
    for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        p.unlink(missing_ok=True)
    fresh = rm.Follower(arena.dir, db, out, log=lambda m: None)
    assert fresh.offset == 0
    fresh.step()
    _same(fresh.conn, tmp_path / "full.sqlite")


def test_a_replica_tick_scans_a_bounded_hot_state(tmp_path, monkeypatch):
    """END_TICK scans every fight, contest, offer and cup the contract holds. A
    replica that never compacted did more of that per tick the longer the
    journal grew: a quadratic replay (90 minutes for 333 MB, 2026-10-06)."""
    _compact_like(monkeypatch, 100, **SMALL)
    arena = _arena(tmp_path)
    for _ in range(3600):
        arena.step()
    arena.save()
    fl = rm.Follower(arena.dir, tmp_path / "rm.sqlite", snapshot=False, log=lambda m: None)
    scanned, end_tick = [], CombatContract.end_tick

    def counting(self, t):
        scanned.append(len(self.fights) + len(self.contests) + len(self.offers) + len(self.cups))
        return end_tick(self, t)
    monkeypatch.setattr(CombatContract, "end_tick", counting)
    while fl.poll():
        pass
    c = fl.replica.contract
    created = sum(c.next_id[k] - 1 for k in ("fight", "contest", "offer", "cup"))
    third = len(scanned) // 3              # never compacted: 54, then 114 (every record); now 33, then 39
    assert max(scanned[-third:]) <= 1.5 * max(scanned[:third]), "a tick's work does not grow with the journal"
    assert max(scanned) < created / 2


def test_a_failed_sync_keeps_what_the_replica_moved_out(tmp_path, monkeypatch):
    """A failed sync rolls back. What the replica moved out waits for the next
    one, and the cursors the failed transaction had moved (open fights and
    contests) are read from the database again, even when that read fails
    at first: no row stays open, and nothing is pruned on cursors that ran
    ahead of the database."""
    _compact_like(monkeypatch, 100, **SMALL)
    arena = _arena(tmp_path)
    db = tmp_path / "inc.sqlite"
    for _ in range(300):
        arena.step()
    arena.save()
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    fl.step()
    live_then = set(fl.syncer.open_fights)
    assert live_then
    for _ in range(900):                       # they finish and leave hot state before the next sync
        arena.step()
    arena.save()
    while fl.poll():
        pass
    held = _archived(fl)
    assert held > 0
    real_fighter, real_init = rm.Syncer._fighter, rm.Syncer.__init__

    def broken(*a):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(rm.Syncer, "_fighter", broken)     # runs after fights, contests, cups and titles
    with pytest.raises(sqlite3.OperationalError):
        fl.sync()
    assert _archived(fl) == held, "kept until a sync commits"
    monkeypatch.setattr(rm.Syncer, "__init__", broken)     # the same trouble: the cursors cannot be read
    for _ in range(100):
        arena.step()
    arena.save()
    with pytest.raises(sqlite3.OperationalError):
        fl.step()
    assert _archived(fl) >= held, "nothing pruned meanwhile"
    monkeypatch.setattr(rm.Syncer, "_fighter", real_fighter)
    monkeypatch.setattr(rm.Syncer, "__init__", real_init)
    for _ in range(50):
        arena.step()
    arena.save()
    fl.step()
    assert _archived(fl) == 0
    assert not live_then & {r[0] for r in fl.conn.execute("SELECT fight_id FROM fights WHERE final = 0")}
    rm.rebuild(arena.dir, tmp_path / "full.sqlite", None, log=lambda m: None)
    _same(fl.conn, tmp_path / "full.sqlite")
    fl.save_snapshot()                         # and a restart resumes from where that left off
    fl.conn.close()
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    assert fl.offset > 0
    for _ in range(100):
        arena.step()
    arena.save()
    fl.step()
    rm.rebuild(arena.dir, tmp_path / "full.sqlite", None, log=lambda m: None)
    _same(fl.conn, tmp_path / "full.sqlite")


def test_a_row_the_replica_dropped_but_the_database_has_open_is_healed(tmp_path, monkeypatch):
    """The replica only forgets records the database holds final, but a hand-
    edited database can reopen one. A restart then refuses a snapshot that
    cannot rewrite it, and a running follower, once it reads its cursors
    again, replays the journal from the start (behind the database) to do so."""
    _compact_like(monkeypatch, 100, **SMALL)
    arena = _arena(tmp_path)
    db = tmp_path / "inc.sqlite"
    fl = None
    for i in range(1, 1201):
        arena.step()
        if i % 50 == 0:
            arena.save()
            fl = fl or rm.Follower(arena.dir, db, log=lambda m: None)
            fl.step()
    gone = [r[0] for r in fl.conn.execute("SELECT fight_id FROM fights WHERE final = 1 ORDER BY fight_id")
            if r[0] not in fl.replica.contract.fights]
    assert len(gone) > 2

    def reopen(fid):
        with fl.conn:
            fl.conn.execute("UPDATE fights SET final = 0 WHERE fight_id = ?", (fid,))

    def final(fid):
        return fl.conn.execute("SELECT final FROM fights WHERE fight_id = ?", (fid,)).fetchone()[0]
    reopen(gone[0])
    fl.save_snapshot()
    fl.conn.close()
    logs = []
    fl = rm.Follower(arena.dir, db, log=logs.append)
    assert fl.offset == 0 and any("missing rows this database has open (fight" in m for m in logs)
    fl.step()
    assert final(gone[0]) == 1
    reopen(gone[1])
    real = rm.Syncer._fighter

    def failing_once(*a):
        monkeypatch.setattr(rm.Syncer, "_fighter", real)
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(rm.Syncer, "_fighter", failing_once)
    for _ in range(20):
        arena.step()
    arena.save()
    with pytest.raises(sqlite3.OperationalError):
        fl.step()
    for _ in range(20):
        arena.step()
    arena.save()
    fl.step()                                  # reads the cursors again: the reopened row is missing
    assert fl.offset == 0 and any("replaying the journal from the start" in m for m in logs)
    fl.step()
    assert final(gone[1]) == 1 and fl.caught_up
    rm.rebuild(arena.dir, tmp_path / "full.sqlite", None, log=lambda m: None)
    _same(fl.conn, tmp_path / "full.sqlite")


def test_a_rebuild_syncs_as_it_goes_and_leaves_a_snapshot_to_resume_from(tmp_path, monkeypatch):
    """A rebuild syncs its private file every REBUILD_SYNC_BYTES, so its replica
    forgets what it compacted (memory stays bounded on a long journal), with
    the same result as syncing once; the API then resumes from its snapshot."""
    _compact_like(monkeypatch, 100, **SMALL)
    arena = _arena(tmp_path)
    for _ in range(1500):
        arena.step()
    arena.save()
    size = (arena.dir / rm.JOURNAL).stat().st_size
    poll, prune, held = rm.Follower.poll, rm.Follower._prune, []

    def pruning(self):
        prune(self)
        held.append(_archived(self))
    monkeypatch.setattr(rm.Follower, "poll", lambda self, max_bytes=16 << 10: poll(self, max_bytes))
    monkeypatch.setattr(rm.Follower, "_prune", pruning)
    monkeypatch.setattr(rm, "REBUILD_SYNC_BYTES", size + 1)            # one sync, at the end
    one = rm.rebuild(arena.dir, tmp_path / "one.sqlite", None, log=lambda m: None)
    once, held[:] = max(held), []
    monkeypatch.setattr(rm, "REBUILD_SYNC_BYTES", size // 8)
    many = rm.rebuild(arena.dir, tmp_path / "many.sqlite", None, log=lambda m: None)
    assert max(held) < once / 2
    assert one["fights"] == many["fights"] == arena.w.contract.next_id["fight"] - 1
    _same(rm.connect(tmp_path / "many.sqlite", readonly=True), tmp_path / "one.sqlite")
    fl = rm.Follower(arena.dir, tmp_path / "many.sqlite", log=lambda m: None)
    assert fl.offset == size, "resumed from the rebuild's snapshot"
    for _ in range(200):
        arena.step()
    arena.save()
    fl.step()
    rm.rebuild(arena.dir, tmp_path / "one.sqlite", None, log=lambda m: None)
    _same(fl.conn, tmp_path / "one.sqlite")


def test_a_long_catch_up_is_saved_at_once_and_a_stop_ends_it(tmp_path, monkeypatch):
    """A stop (SIGTERM) ends a catch-up between chunks and run() saves where it
    got to; a catch-up of SNAPSHOT_AFTER_BYTES or more is saved as soon as it
    is done, not SNAPSHOT_EVERY_S later: a restart need not repeat it."""
    arena = _arena(tmp_path)
    for _ in range(400):
        arena.step()
    arena.save()
    size = (arena.dir / rm.JOURNAL).stat().st_size
    db, poll, stop = tmp_path / "rm.sqlite", rm.Follower.poll, threading.Event()

    def poll_then_stop(self, max_bytes=16 << 10):
        n = poll(self, max_bytes)
        stop.set()                             # SIGTERM during the catch-up
        return n
    monkeypatch.setattr(rm.Follower, "poll", poll_then_stop)
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    fl.run(stop)
    assert 0 < fl.offset < size and not fl.caught_up and rm.get_meta(fl.conn, "tick") is None
    with open(db.with_suffix(".replica"), "rb") as f:
        assert rm.snapshot_head(f)["offset"] == fl.offset
    fl.conn.close()
    monkeypatch.setattr(rm.Follower, "poll", lambda self, max_bytes=16 << 10: poll(self, max_bytes))
    monkeypatch.setattr(rm, "SNAPSHOT_AFTER_BYTES", size // 2)
    stopped_at = fl.offset
    fl = rm.Follower(arena.dir, db, log=lambda m: None)
    assert fl.offset == stopped_at
    fl.step()
    assert fl.caught_up and fl.offset == size
    with open(db.with_suffix(".replica"), "rb") as f:
        head = rm.snapshot_head(f)
    assert head["offset"] == head["db_offset"] == size


def test_a_journal_replaced_by_an_arena_under_other_rules_is_replayed_under_them(tmp_path):
    arena = _arena(tmp_path)
    for _ in range(60):
        arena.step()
    arena.save()
    fl = rm.Follower(arena.dir, tmp_path / "rm.sqlite", snapshot=False, log=lambda m: None)
    fl.step()
    arena.dir.rename(tmp_path / "moved-aside")             # a rules change: a fresh arena in its place
    other = live.Arena(tmp_path / "arena", LINEUP, profile="demo-c2", seed=11, deterministic=True,
                       cup_every=500, duel_every=90, market_every=0, log=lambda m: None)
    for _ in range(80):
        other.step()
    other.save()
    fl.step()
    assert fl.m == other.net.m and fl.m != arena.net.m
    assert fl.replica.contract.event_digest == other.w.contract.event_digest
