import json

from qdojo.combat import live


def test_live_run_exports_pruned_data_and_resumes(tmp_path):
    out = tmp_path / "web" / "combat" / "v1"
    lineup = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"},
              {"label": "c", "policy": "mixed-v1"}]
    live.run(tmp_path / "net", lineup, out, tick_seconds=0, export_every=40, keep=3, ticks=500, log=lambda m: None)
    index = json.loads((out / "index.json").read_text())
    assert index["deployment"]["kind"] == "devnet" and index["deployment"]["currency"] == "fake QU"
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
