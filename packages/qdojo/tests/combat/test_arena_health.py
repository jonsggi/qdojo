"""Arena health (AUD-024, AUD-025): the export against the contract, the
steady-state soak phase, snapshots and compaction of finished history."""
import collections
import importlib.util
import json
from pathlib import Path

from qdojo.combat import export, invariants, live

ROOT = Path(__file__).resolve().parents[4]
LINEUP = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"},
          {"label": "c", "policy": "mixed-v1"}]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _arena(tmp_path, lineup=LINEUP, **kw):
    return live.Arena(tmp_path / "arena", lineup, seed=5, deterministic=True, log=lambda m: None, **kw)


# ---- AUD-025: published fights against the contract ------------------------

def test_check_export_catches_a_fight_frozen_mid_round(tmp_path, monkeypatch):
    # Reinstate the AUD-011 exporter bug (a file that exists is never rewritten)
    # and require the invariant to catch the frozen file once the fight ends.
    monkeypatch.setattr(export, "_written_final", lambda p: p.exists())
    arena = _arena(tmp_path)
    root = tmp_path / "combat" / "v1"
    found = []
    for i in range(1, 1200):
        arena.step()
        if i % 5 == 0:
            export.export_all(arena.w.contract, root, keep=100, deployment=arena.deployment(0))
            found = invariants.check_export(arena.w.contract, root, slack=6)
            if found:
                break
    assert found and any("still publishes it" in x or "overdue" in x for x in found), found
    # The fixed exporter rewrites the file, and the export checks clean again.
    monkeypatch.undo()
    export.export_all(arena.w.contract, root, keep=100, deployment=arena.deployment(0))
    assert invariants.check_export(arena.w.contract, root, slack=6) == []


def test_check_export_flags_an_overdue_live_file(tmp_path):
    arena = _arena(tmp_path)
    root = tmp_path / "combat" / "v1"
    while not any(f.phase != "DONE" for f in arena.w.contract.fights.values()):
        arena.step()
    export.export_all(arena.w.contract, root, keep=100, deployment=arena.deployment(0))
    assert invariants.check_export(arena.w.contract, root, slack=6) == []
    live_id = next(f for f, x in arena.w.contract.fights.items() if x.phase != "DONE")
    stale = json.loads((root / "fights" / f"{live_id}.json").read_text())
    for _ in range(80):                                   # the export stops; the chain goes on
        arena.step()
    (root / "fights" / f"{live_id}.json").write_text(json.dumps(stale))
    problems = invariants.check_export(arena.w.contract, root, slack=6)
    assert any(f"fight {live_id}" in x for x in problems), problems


def test_steady_soak_phase_exports_cleanly_with_a_power_reusing_planner():
    soak = _script("combat-soak")
    problems, stats = soak.steady(ticks=500, seed=3, export_every=6, drop_rate=0.02)
    assert problems == [], problems
    assert stats["exports"] > 50 and stats["power_slots_stripped"] > 0
    assert "reveal:BAD_PLAN" not in stats["rejections"]


def test_bots_count_final_rejections(tmp_path):
    arena = _arena(tmp_path, [{"label": "x", "stub": "power-reuse"}, {"label": "y", "policy": "mixed-v1"}])
    for _ in range(400):
        arena.step()
    total = sum((b.rejected for b in arena.bots.values()), collections.Counter())
    assert total["reveal:BAD_PLAN"] == 0
    assert any(arena.deployment(0)["fighters"][f.hex()]["driver"] == "stub:power-reuse" for f in arena.bots)


# ---- AUD-024: compaction and snapshots ----------------------------------------

def _state(w):
    c = w.contract
    return {"tick": w.tick, "event": (c.event_seq, c.event_digest), "credits": dict(c.ledger.credits),
            "balance": c.ledger.balance, "balances": dict(w.balances),
            "fighters": {f: (x.lifetime, dict(x.record), x.placement, x.lock, x.cooldown_until)
                         for f, x in c.fighters.items()}}


def test_compaction_is_transparent_to_the_arena(tmp_path, monkeypatch):
    # Same seed, with and without compaction: bots read scouting history and
    # settle budgets from compacted state, and nothing they do changes.
    lineup = [dict(e) for e in live.DEFAULT_LINEUP] + [{"label": "ronin", "policy": "mixed-v1", "reliability": 0.3}]
    from qdojo.combat import store
    runs = {}
    # Tight retention, so this short run really prunes.
    monkeypatch.setattr(live, "compact", lambda c: store.compact(c, keep_ticks=300, keep_recent=10, keep_cups=2))
    for every in (300, 10**9):
        monkeypatch.setattr(live, "COMPACT_EVERY", every)
        arena = live.Arena(tmp_path / f"arena-{every}", lineup, seed=11, deterministic=True, log=lambda m: None,
                           cup_every=700, duel_every=100, snapshot_every=0)
        for _ in range(2400):
            arena.step()
        runs[every] = arena
    small, full = runs[300].w.contract, runs[10**9].w.contract
    assert _state(runs[300].w) == _state(runs[10**9].w)
    assert len(small.fights) < len(full.fights) and small.history.pruned["fights"] > 0
    assert export.records_by_mode(small) == export.records_by_mode(full)
    assert export.fighter_fights(small) == export.fighter_fights(full)
    from qdojo.combat import scouting
    for fid in full.fighters:
        assert scouting.Scout().history(small, fid, -1, small.tick) == scouting.Scout().history(full, fid, -1, full.tick)
    for b in runs[300].bots.values():
        assert all(s.returned is not None or not s.contest_or_offer.startswith("contest:") or
                   int(s.contest_or_offer.split(":")[1]) in small.contests for s in b.bstate.spends)


def _run(tmp_path, ticks, **kw):
    out = tmp_path / "web" / "combat" / "v1"
    return live.run(tmp_path / "net", LINEUP, out, tick_seconds=0, export_every=10, keep=50, ticks=ticks,
                    log=lambda m: None, seed=3, deterministic=True, **kw)


def test_a_snapshot_restart_equals_a_full_replay(tmp_path):
    from qdojo.combat import devnet
    arena = _run(tmp_path, 2700)
    net_dir = tmp_path / "net"
    assert (net_dir / devnet.SNAPSHOT).exists() and (net_dir / devnet.SNAPSHOT_PREV).exists()
    fast = devnet.Devnet(net_dir, compact=live.compact, compact_every=live.COMPACT_EVERY)
    assert fast.restart["mode"] == "snapshot snapshot.pickle" and not fast.restart["tried"]
    assert _state(fast.world) == _state(arena.w)
    for name in (devnet.SNAPSHOT, devnet.SNAPSHOT_PREV):
        (net_dir / name).rename(net_dir / (name + ".off"))
    slow = devnet.Devnet(net_dir, compact=live.compact, compact_every=live.COMPACT_EVERY)
    assert slow.restart["mode"] == "full replay"
    assert _state(slow.world) == _state(arena.w)
    assert export.records_by_mode(slow.world.contract) == export.records_by_mode(fast.world.contract)
    # A restarted arena carries on from the snapshot.
    for name in (devnet.SNAPSHOT, devnet.SNAPSHOT_PREV):
        (net_dir / (name + ".off")).rename(net_dir / name)
    again = _run(tmp_path, 30)
    assert again.w.tick == arena.w.tick + 30


def test_a_snapshot_that_does_not_verify_falls_back(tmp_path):
    from qdojo.combat import devnet
    arena = _run(tmp_path, 2500)
    net_dir = tmp_path / "net"
    want = _state(arena.w)
    snap = net_dir / devnet.SNAPSHOT
    blob = bytearray(snap.read_bytes())
    blob[-10] ^= 0xFF                                     # a flipped payload byte
    snap.write_bytes(bytes(blob))
    net = devnet.Devnet(net_dir)
    assert net.restart["mode"] == "snapshot snapshot.prev.pickle" and "payload hash" in net.restart["tried"][0]
    assert _state(net.world) == want
    # A journal that does not continue the snapshots' journal: full replay.
    prev = net_dir / devnet.SNAPSHOT_PREV
    head = json.loads(prev.read_bytes().split(b"\n", 1)[0])
    head["journal_sha256"] = "00" * 32
    prev.write_bytes(json.dumps(head).encode() + b"\n" + prev.read_bytes().split(b"\n", 1)[1])
    net = devnet.Devnet(net_dir)
    assert net.restart["mode"] == "full replay" and "does not continue" in net.restart["tried"][1]
    assert _state(net.world) == want


def test_a_diverging_replay_is_caught_at_a_checkpoint(tmp_path):
    from qdojo.combat import devnet, store
    _run(tmp_path, 1300)
    net_dir = tmp_path / "net"
    for name in (devnet.SNAPSHOT, devnet.SNAPSHOT_PREV):
        (net_dir / name).unlink(missing_ok=True)
    lines = (net_dir / devnet.JOURNAL).read_text().splitlines()
    i = max(n for n, x in enumerate(lines) if '"k":"digest"' in x)
    rec = json.loads(lines[i])
    rec["event_digest"] = "11" * 32
    lines[i] = json.dumps(rec, separators=(",", ":"))
    (net_dir / devnet.JOURNAL).write_text("\n".join(lines) + "\n")
    try:
        devnet.Devnet(net_dir)
    except store.StoreError as exc:
        assert "checkpoint" in str(exc)
    else:
        raise AssertionError("a wrong checkpoint must stop the replay")


def test_a_torn_final_journal_line_is_dropped(tmp_path):
    from qdojo.combat import devnet
    arena = _run(tmp_path, 200, snapshot_every=0)
    path = tmp_path / "net" / devnet.JOURNAL
    with open(path, "a") as f:
        f.write('{"k":"call","t":')
    net = devnet.Devnet(tmp_path / "net")
    assert net.world.tick == arena.w.tick and path.read_bytes().endswith(b"\n")


def test_existing_arenas_keep_their_recorded_manifest(tmp_path, monkeypatch):
    from qdojo.combat import devnet
    net = devnet.Devnet(tmp_path / "net", "demo")
    net.save()
    meta = json.loads((tmp_path / "net" / devnet.MARKER).read_text())
    assert meta["params"]["timing"] == {"1": list(devnet.DEMO_TIMING)}
    monkeypatch.setitem(devnet.PROFILES, "demo", {**devnet.PROFILES["demo"], "pair_starts_per_epoch": 1})
    assert devnet.Devnet(tmp_path / "net").m.pair_starts_per_epoch == meta["params"]["pair_starts_per_epoch"]
    # An arena from before devnet.json recorded values replays with the legacy demo values.
    del meta["params"]
    (tmp_path / "net" / devnet.MARKER).write_text(json.dumps(meta))
    assert devnet.Devnet(tmp_path / "net").m.pair_starts_per_epoch == 6


def test_index_json_carries_bounded_ownership_history(tmp_path):
    dep = {"fighters": {"aa": {"name": "x", "asset": {"owner": "o9", "history": [
        {"tick": str(t), "from": f"o{t - 1}" if t else None, "to": f"o{t}"} for t in range(10)]}}}}
    idx = export.index_deployment(dep)["fighters"]["aa"]["asset"]
    assert len(idx["history"]) == export.INDEX_HISTORY and idx["transfers"] == 9 and idx["history_truncated"]
    assert idx["history"][-1]["to"] == "o9" and len(dep["fighters"]["aa"]["asset"]["history"]) == 10
